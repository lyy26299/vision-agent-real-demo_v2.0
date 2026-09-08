"""Qwen adapter completion/barge-in fixes for the pinned vision-agents 0.6.9."""

import asyncio
import base64
import contextlib
import inspect
from collections.abc import Awaitable, Callable

from getstream.video.rtc import PcmData
from vision_agents.plugins.qwen import Realtime

from coach.qwen_contract import build_response_create_event, build_text_input_event


class DuplexQwenRealtime(Realtime):
    """Qwen Realtime adapter with interruption-safe text injection.

    The pinned Vision-Agents adapter intentionally leaves ``simple_response``
    empty because Qwen Realtime does not expose that older helper contract.
    The DashScope websocket does accept a conversation ``input_text`` item,
    so the memory/agent layer uses :meth:`inject_text` instead.  User
    transcription callbacks are scheduled away from the websocket reader so
    a slow retrieval operation cannot stall audio/video ingestion.
    """

    def __init__(
        self,
        *args,
        user_transcript_sink: Callable[[str], Awaitable[None] | None] | None = None,
        feedback_sink: Callable[[str, str | None, str | None], Awaitable[None] | None]
        | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.user_transcript_sink = user_transcript_sink
        self.feedback_sink = feedback_sink
        self._transcript_tasks: set[asyncio.Task] = set()
        self._feedback_tasks: set[asyncio.Task] = set()
        self._active_feedback_id: str | None = None
        self._active_feedback_response_id: str | None = None

    async def inject_text(
        self,
        text: str,
        *,
        interrupt: bool = True,
        feedback_id: str | None = None,
    ) -> bool:
        """Ask the active Qwen session to speak a validated text instruction.

        This is an application-to-model control message, not a user utterance
        and not an authoritative training fact.  The caller is responsible
        for bounding and validating ``text`` before it reaches this method.
        """

        text = str(text).strip()
        if not text or not self.connected:
            return False
        if interrupt:
            await self._on_interruption()
        self._active_feedback_id = feedback_id
        self._active_feedback_response_id = None
        await self._client.send_event(build_text_input_event(text))
        await self._client.send_event(build_response_create_event())
        self._schedule_feedback_sink("queued", feedback_id, None)
        return True

    def _schedule_transcript_sink(self, text: str) -> None:
        sink = self.user_transcript_sink
        if sink is None:
            return
        try:
            result = sink(text)
        except Exception:
            # A transcript observer must never terminate the Qwen reader.
            return
        if not inspect.isawaitable(result):
            return
        task = asyncio.create_task(result)
        self._transcript_tasks.add(task)
        task.add_done_callback(self._transcript_tasks.discard)

    def _schedule_feedback_sink(
        self, state: str, feedback_id: str | None, response_id: str | None
    ) -> None:
        sink = self.feedback_sink
        if sink is None or not feedback_id:
            return
        try:
            result = sink(state, feedback_id, response_id)
        except Exception:
            return
        if not inspect.isawaitable(result):
            return
        task = asyncio.create_task(result)
        self._feedback_tasks.add(task)
        task.add_done_callback(self._feedback_tasks.discard)

    async def close(self):
        # Upstream 0.6.9 lets CancelledError skip websocket/executor cleanup.
        if self._processing_task is not None:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
            self._processing_task = None
        if self._transcript_tasks:
            await asyncio.gather(*self._transcript_tasks, return_exceptions=True)
            self._transcript_tasks.clear()
        if self._feedback_tasks:
            await asyncio.gather(*self._feedback_tasks, return_exceptions=True)
            self._feedback_tasks.clear()
        await super().close()

    async def _process_events(self):
        # Generation IDs prevent late packets from a cancelled response restarting playback.
        cancelled = set()
        async for event in self._client.read():
            kind = event.get("type")
            response_id = event.get("response_id")
            if kind == "error":
                self._emit_error_event(
                    error=Exception(str(event.get("error"))), context="qwen_realtime_api"
                )
            elif kind == "response.created":
                self._current_response_id = event.get("response", {}).get("id")
                self._is_responding = True
                self._active_feedback_response_id = self._current_response_id
                self._schedule_feedback_sink(
                    "generated", self._active_feedback_id, self._active_feedback_response_id
                )
            elif kind == "response.output_item.added":
                self._current_item_id = event.get("item", {}).get("id")
            elif kind == "input_audio_buffer.speech_started":
                # Also flush when server generation has ended but local playout has not.
                self._emit_audio_output_done_event(interrupted=True)
                self._emit_user_speech_started()
                if self._current_response_id:
                    cancelled.add(self._current_response_id)
                await self._on_interruption()
            elif kind == "input_audio_buffer.speech_stopped":
                self._emit_user_speech_ended()
            elif kind == "response.done":
                done_id = event.get("response", {}).get("id")
                if done_id not in cancelled:
                    self._emit_audio_output_done_event(response_id=done_id)
                    self._emit_agent_speech_transcription(text="", mode="final")
                    self._schedule_feedback_sink("completed", self._active_feedback_id, done_id)
                if done_id == self._current_response_id or done_id is None:
                    self._is_responding = False
                    self._current_response_id = None
                    self._current_item_id = None
                    self._active_feedback_id = None
                    self._active_feedback_response_id = None
                cancelled.discard(done_id)
            elif kind == "response.audio.delta":
                if (
                    self._is_responding
                    and response_id not in cancelled
                    and response_id in (None, self._current_response_id)
                ):
                    self._emit_audio_output_event(
                        pcm=PcmData.from_bytes(base64.b64decode(event["delta"]), 24000),
                        response_id=response_id,
                    )
            elif kind == "conversation.item.input_audio_transcription.completed":
                if text := event.get("transcript", ""):
                    self._emit_user_speech_transcription(text=text, mode="final")
                    self._schedule_transcript_sink(text)
            elif (
                kind == "response.audio_transcript.delta"
                and response_id not in cancelled
                and (text := event.get("delta", ""))
            ):
                self._emit_agent_speech_transcription(text=text, mode="delta")

    async def _on_interruption(self):
        if not self._is_responding:
            return
        if self._current_response_id:
            await self._client.cancel_response()
        self._schedule_feedback_sink(
            "interrupted", self._active_feedback_id, self._current_response_id
        )
        self._is_responding = False
        self._current_response_id = None
        self._current_item_id = None
        self._active_feedback_id = None
        self._active_feedback_response_id = None
