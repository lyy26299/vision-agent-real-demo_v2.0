"""Loopback WebRTC transport: browser owns capture, AEC and speaker rendering."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
from aiohttp import web
from aiortc import (
    AudioStreamTrack,
    MediaStreamError,
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
)
from getstream.video.rtc import PcmData
from getstream.video.rtc.track_util import FrameResampler
from vision_agents.core.agents.conversation import InMemoryConversation
from vision_agents.core.edge import EdgeTransport
from vision_agents.core.edge.events import (
    AudioReceivedEvent,
    ParticipantJoinedEvent,
    ParticipantLeftEvent,
    TrackAddedEvent,
    TrackRemovedEvent,
)
from vision_agents.core.edge.types import Connection, Participant, TrackType

LOGGER = logging.getLogger("vision_coach")


class BrowserAudioTrack(AudioStreamTrack):
    """Continuous 48 kHz render clock; no microphone muting during playback."""

    def __init__(self):
        super().__init__()
        self.frames = deque()
        self.resampler = FrameResampler(48000, "mono", "s16", 960)
        self.active = False
        self._pts = 0
        self._deadline = None
        self._space = asyncio.Event()
        self._generation = 0

    async def write(self, data: PcmData, final: bool = False):
        if not self.active or self.readyState != "live":
            return
        frames = self.resampler.resample(data, flush=final)
        generation = self._generation
        for frame in frames:
            while len(self.frames) >= 25 and generation == self._generation and self.active:
                self._space.clear()
                await self._space.wait()
            if generation != self._generation or not self.active or self.readyState != "live":
                return
            self.frames.append(frame)

    async def flush(self):
        self._generation += 1
        self.frames.clear()
        self.resampler = FrameResampler(48000, "mono", "s16", 960)
        self._space.set()

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        loop = asyncio.get_running_loop()
        if self._deadline is not None:
            await asyncio.sleep(max(0, self._deadline - loop.time()))
        if self.readyState != "live":
            raise MediaStreamError
        if self.frames:
            frame = self.frames.popleft()
            self._space.set()
        else:
            frame = av.AudioFrame(format="s16", layout="mono", samples=960)
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
        frame.sample_rate = 48000
        frame.pts = self._pts
        frame.time_base = Fraction(1, 48000)
        self._pts += frame.samples
        self._deadline = max(self._deadline or loop.time(), loop.time()) + frame.samples / 48000
        return frame

    def stop(self):
        self.active = False
        self._space.set()
        self.frames.clear()
        super().stop()


@dataclass
class BrowserCall:
    id: str


class BrowserConnection(Connection):
    def __init__(self, edge):
        self.edge = edge

    async def close(self, **kwargs):
        await self.edge.close()

    async def wait_for_participant(self, timeout=None):
        await asyncio.wait_for(self.edge.connected.wait(), timeout)

    def idle_since(self):
        return 0.0 if self.edge.connected.is_set() else self.edge.idle_at


class BrowserEdge(EdgeTransport):
    """One browser per training session, authenticated loopback signaling only."""

    def __init__(self, frame_sink: Callable[[Any], None] | None = None):
        super().__init__()
        self.frame_sink = frame_sink
        self.token = secrets.token_urlsafe(32)
        self.connected = asyncio.Event()
        self.finished = asyncio.Event()
        self.published = asyncio.Event()
        self.idle_at = time.time()
        self.failure = ""
        self.url = ""
        self.call = None
        self.pc = None
        self.runner = None
        self.audio = BrowserAudioTrack()
        self.video = {}
        self.tasks = set()
        self.participant = Participant(original=None, user_id="browser", id="browser")
        self._offer_lock = asyncio.Lock()
        self._closed = False

    def _task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def create_audio_track(self):
        return self.audio

    async def authenticate(self, user):
        pass

    async def create_call(self, call_id, **kwargs):
        return BrowserCall(call_id)

    async def create_conversation(self, call, user, instructions):
        return InMemoryConversation(instructions=instructions, messages=[])

    def open_demo(self, *args, **kwargs):
        if self.url:
            try:
                if webbrowser.get(os.getenv("COACH_BROWSER", "chrome")).open(self.url):
                    return
            except webbrowser.Error:
                pass
            LOGGER.info("首选浏览器未打开，尝试系统默认浏览器")
            webbrowser.open(self.url)

    async def open_demo_for_agent(self, *args, **kwargs):
        pass

    async def join(self, agent, call, **kwargs):
        self.call = call
        app = web.Application(client_max_size=128 * 1024)
        app.router.add_get("/", self._page)
        app.router.add_post("/offer", self._offer)
        app.router.add_post("/stop", self._stop)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        self.origin = f"http://127.0.0.1:{port}"
        self.url = f"{self.origin}/?token={self.token}"
        return BrowserConnection(self)

    def _authorize(self, request):
        if not secrets.compare_digest(request.query.get("token", ""), self.token):
            raise web.HTTPForbidden(text="会话链接已失效")
        if request.headers.get("Origin", self.origin) != self.origin:
            raise web.HTTPForbidden(text="仅允许本地同源访问")

    async def _page(self, request):
        self._authorize(request)
        return web.Response(
            text=Path(__file__).with_name("browser_media.html").read_text(),
            content_type="text/html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def _stop(self, request):
        self._authorize(request)
        self.finished.set()
        return web.json_response({"ok": True})

    async def _offer(self, request):
        self._authorize(request)
        try:
            data = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="无效的会话请求")
        if (
            not isinstance(data, dict)
            or data.get("type") != "offer"
            or not isinstance(data.get("sdp"), str)
        ):
            raise web.HTTPBadRequest(text="缺少 SDP offer")
        if data.get("aec") is not True:
            raise web.HTTPBadRequest(text="浏览器未确认启用回声消除，请使用支持 AEC 的浏览器")
        async with self._offer_lock:
            if self.pc is not None or self._closed or self.finished.is_set():
                raise web.HTTPConflict(text="此训练已连接或结束，请在桌面重新开始训练")
            try:
                await asyncio.wait_for(self.published.wait(), 15)
                pc = self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

                @pc.on("track")
                def on_track(track):
                    if track.kind == "audio":
                        self._task(self._receive_audio(track))
                    elif track.kind == "video":
                        self.video[track.id] = track
                        self.events.send(
                            TrackAddedEvent(
                                plugin_name="browser",
                                track_id=track.id,
                                track_type=TrackType.VIDEO,
                                participant=self.participant,
                            )
                        )

                    @track.on("ended")
                    def ended():
                        self.video.pop(track.id, None)
                        self.events.send(
                            TrackRemovedEvent(
                                plugin_name="browser",
                                track_id=track.id,
                                track_type=(
                                    TrackType.AUDIO if track.kind == "audio" else TrackType.VIDEO
                                ),
                                participant=self.participant,
                            )
                        )

                @pc.on("connectionstatechange")
                async def state_changed():
                    if pc.connectionState == "connected":
                        self.audio.active = True
                        self.connected.set()
                        self.events.send(
                            ParticipantJoinedEvent(
                                plugin_name="browser",
                                participant=self.participant,
                                call=self.call,
                            )
                        )
                        LOGGER.info("浏览器音视频已连接，AEC 已由浏览器确认启用")
                    elif pc.connectionState in {"failed", "closed"}:
                        self.audio.active = False
                        await self.audio.flush()
                        self.connected.clear()
                        self.idle_at = time.time()
                        self.finished.set()

                await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="offer"))
                pc.addTrack(self.audio)
                await pc.setLocalDescription(await pc.createAnswer())
                return web.json_response({"sdp": pc.localDescription.sdp, "type": "answer"})
            except Exception:
                self.failure = "浏览器 WebRTC 连接失败，请重新开始训练"
                self.finished.set()
                LOGGER.exception(self.failure)
                raise web.HTTPBadRequest(text=self.failure)

    async def _receive_audio(self, track):
        try:
            while True:
                pcm = PcmData.from_av_frame(await track.recv()).resample(48000, target_channels=1)
                pcm.participant = self.participant
                self.events.send(
                    AudioReceivedEvent(
                        plugin_name="browser",
                        pcm_data=pcm,
                        participant=self.participant,
                    )
                )
        except MediaStreamError:
            self.finished.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failure = "浏览器音频流异常"
            LOGGER.exception(self.failure)
            self.finished.set()

    def add_track_subscriber(self, track_id):
        return self.video.get(track_id)

    async def publish_tracks(self, audio_track, video_track):
        if audio_track is not self.audio:
            raise ValueError("BrowserEdge requires its own audio track")
        if video_track is not None:
            self._task(self._forward_video(video_track))
        self.published.set()

    async def _forward_video(self, source):
        try:
            while True:
                frame = await source.recv()
                if self.frame_sink:
                    self.frame_sink(frame)
        except (MediaStreamError, RuntimeError):
            LOGGER.debug("教练视频输出已结束")

    async def send_custom_event(self, data):
        raise NotImplementedError("BrowserEdge has no custom event channel")

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self.finished.set()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.pc:
            await self.pc.close()
        self.audio.stop()
        self.video.clear()
        self.connected.clear()
        if self.call:
            self.events.send(
                ParticipantLeftEvent(
                    plugin_name="browser",
                    participant=self.participant,
                    call=self.call,
                )
            )
        if self.runner:
            await self.runner.cleanup()
