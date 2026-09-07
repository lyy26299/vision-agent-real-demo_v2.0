"""Agent runtime for the local Vision Coach desktop application."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import ssl
import uuid
from collections.abc import Callable
from typing import Any, Protocol

import certifi
from dotenv import load_dotenv

from coach.qwen_contract import CHINA_BASE_URL, QWEN_REALTIME_MODEL

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
load_dotenv()

try:
    import aiohttp.connector

    cached_context = aiohttp.connector._SSL_CONTEXT_VERIFIED
    if not cached_context.get_ca_certs():
        aiohttp.connector._SSL_CONTEXT_VERIFIED = ssl.create_default_context(
            cafile=os.environ["SSL_CERT_FILE"]
        )
except (ImportError, AttributeError, OSError):
    pass


LOGGER = logging.getLogger("vision_coach")


class SessionSettings(Protocol):
    audio_input: Any
    audio_output: Any
    camera: Any
    exercise: str
    target_reps: int


class CoachUI(Protocol):
    alive: bool

    @property
    def state(self) -> str: ...

    def set_state(self, state: str, detail: str = "") -> None: ...

    def submit_frame(self, frame: Any) -> None: ...

    def append_log(self, text: str, tag: str = "normal") -> None: ...


def make_dashboard_edge(settings: SessionSettings, frame_sink: Callable[[Any], None]) -> Any:
    """Create a LocalEdge that renders processed frames in the main dashboard."""

    import aiortc
    from vision_agents.plugins.local import LocalEdge

    class DashboardLocalEdge(LocalEdge):
        async def _forward_video(self, source: aiortc.MediaStreamTrack) -> None:
            try:
                while True:
                    frame = await source.recv()
                    frame_sink(frame)
            except asyncio.CancelledError:
                raise
            except (aiortc.MediaStreamError, RuntimeError):
                LOGGER.debug("本地视频流已结束")

        async def open_demo_for_agent(self, *_args: Any, **_kwargs: Any) -> None:
            return

    return DashboardLocalEdge(
        audio_input=settings.audio_input,
        audio_output=settings.audio_output,
        video_input=settings.camera,
        video_width=640,
        video_height=480,
        video_fps=30,
    )


def session_instructions(settings: SessionSettings) -> str:
    return (
        "Read @docs/COACHING_INSTRUCTIONS.md\n\n"
        f"本次训练项目：{settings.exercise}。目标：{settings.target_reps} 次。"
        "优先观察这个动作，清晰计数，并只在必要时给出一句纠正。"
    )


def valid_dashscope_key() -> bool:
    value = os.getenv("DASHSCOPE_API_KEY", "").strip()
    return bool(value and value != "your_dashscope_api_key_here")


class SessionController:
    """Own the Vision Agent lifecycle without depending on Tkinter."""

    def __init__(self, ui: CoachUI) -> None:
        self.ui = ui
        self.task: asyncio.Task[None] | None = None
        self.stop_event: asyncio.Event | None = None

    def start(self, settings: SessionSettings) -> None:
        if self.task is not None and not self.task.done():
            return
        self.stop_event = asyncio.Event()
        self.task = asyncio.create_task(self._run(settings), name="local-fitness-session")

    def stop(self) -> None:
        if self.stop_event is not None:
            self.ui.set_state("stopping")
            self.stop_event.set()

    async def shutdown(self) -> None:
        if self.task is not None and not self.task.done():
            self.stop()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self.task, timeout=8)

    async def _run(self, settings: SessionSettings) -> None:
        agent = None
        processor = None
        try:
            if not valid_dashscope_key():
                raise RuntimeError("请先在 .env 中配置 DASHSCOPE_API_KEY")

            self.ui.set_state("starting", "正在加载姿态模型")
            LOGGER.info("正在加载 YOLO 姿态模型...")

            from vision_agents.core import Agent, User
            from vision_agents.plugins import qwen, ultralytics

            processor = await asyncio.to_thread(
                ultralytics.YOLOPoseProcessor,
                model_path="yolo11n-pose.pt",
                device=os.getenv("YOLO_DEVICE", "mps"),
                fps=10,
                max_workers=2,
            )
            if self.stop_event is None or self.stop_event.is_set():
                return

            self.ui.set_state("starting", "正在连接实时教练")
            edge = make_dashboard_edge(settings, self.ui.submit_frame)
            agent = Agent(
                edge=edge,
                agent_user=User(name="AI 健身教练"),
                instructions=session_instructions(settings),
                llm=qwen.Realtime(
                    model=os.getenv("QWEN_REALTIME_MODEL", QWEN_REALTIME_MODEL),
                    fps=1,
                    include_video=True,
                    base_url=os.getenv(
                        "DASHSCOPE_BASE_URL",
                        CHINA_BASE_URL,
                    ),
                    voice=os.getenv("QWEN_VOICE", "Ethan"),
                    vad_threshold=0.35,
                ),
                processors=[processor],
            )

            call_id = f"local-{uuid.uuid4().hex[:8]}"
            call = await agent.create_call("local", call_id)
            async with agent.join(call, participant_wait_timeout=0):
                self.ui.set_state("running", f"{settings.exercise} · {settings.target_reps} 次")
                LOGGER.info("训练已开始，请保持全身位于画面内并直接说话。")
                if self.stop_event is not None:
                    await self.stop_event.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("训练启动失败")
            self.ui.set_state("error", "启动失败")
            self.ui.append_log(str(exc), "error")
        finally:
            if agent is not None:
                with contextlib.suppress(Exception):
                    await agent.close()
            elif processor is not None:
                with contextlib.suppress(Exception):
                    await processor.close()
            if self.ui.alive and self.ui.state != "error":
                self.ui.set_state("idle", "待命")
                LOGGER.info("训练已停止。")
