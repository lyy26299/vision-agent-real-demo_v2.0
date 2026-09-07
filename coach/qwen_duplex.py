"""Qwen adapter completion/barge-in fixes for the pinned vision-agents 0.6.9."""

import asyncio
import base64
import contextlib

from getstream.video.rtc import PcmData
from vision_agents.plugins.qwen import Realtime


class DuplexQwenRealtime(Realtime):
    async def close(self):
        # Upstream 0.6.9 lets CancelledError skip websocket/executor cleanup.
        if self._processing_task is not None:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
            self._processing_task = None
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
                if done_id == self._current_response_id or done_id is None:
                    self._is_responding = False
                    self._current_response_id = None
                    self._current_item_id = None
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
            elif (
                kind == "response.audio_transcript.delta"
                and response_id not in cancelled
                and (text := event.get("delta", ""))
            ):
                self._emit_agent_speech_transcription(text=text, mode="delta")
