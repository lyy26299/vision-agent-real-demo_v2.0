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

from coach.models import PoseSnapshot
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
    exercise: str
    target_reps: int


class CoachUI(Protocol):
    alive: bool

    @property
    def state(self) -> str: ...

    def set_state(self, state: str, detail: str = "") -> None: ...

    def submit_frame(self, frame: Any) -> None: ...

    def begin_pose_session(self, session_id: str) -> None: ...

    def submit_pose(self, snapshot: PoseSnapshot) -> None: ...

    def append_log(self, text: str, tag: str = "normal") -> None: ...


def make_dashboard_edge(settings: SessionSettings, frame_sink: Callable[[Any], None]) -> Any:
    """Browser owns device I/O; processed video stays in the dashboard."""
    from coach.browser_edge import BrowserEdge

    return BrowserEdge(frame_sink=frame_sink)


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
        edge = None
        waiters = []
        try:
            if not valid_dashscope_key():
                raise RuntimeError("请先在 .env 中配置 DASHSCOPE_API_KEY")

            self.ui.set_state("starting", "正在加载姿态模型")
            LOGGER.info("正在加载 YOLO 姿态模型...")

            from vision_agents.core import Agent, User

            from coach.pose_adapter import StructuredPoseProcessor
            from coach.qwen_duplex import DuplexQwenRealtime

            call_id = f"local-{uuid.uuid4().hex[:8]}"
            self.ui.begin_pose_session(call_id)
            processor = await asyncio.to_thread(
                StructuredPoseProcessor,
                session_id=call_id,
                snapshot_sink=self.ui.submit_pose,
                model_path="yolo11n-pose.pt",
                device=os.getenv("YOLO_DEVICE", "mps"),
                fps=10,
            )
            if self.stop_event is None or self.stop_event.is_set():
                return

            self.ui.set_state("starting", "正在连接实时教练")
            edge = make_dashboard_edge(settings, self.ui.submit_frame)
            agent = Agent(
                edge=edge,
                agent_user=User(name="AI 健身教练"),
                instructions=session_instructions(settings),
                llm=DuplexQwenRealtime(
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

            call = await agent.create_call("local", call_id)
            async with agent.join(call, participant_wait_timeout=0):
                self.ui.set_state("starting", "等待浏览器授权")
                LOGGER.info("请打开浏览器链接并连接音视频设备：%s", edge.url)
                await asyncio.to_thread(edge.open_demo)
                stop_wait = asyncio.create_task(self.stop_event.wait())
                end_wait = asyncio.create_task(edge.finished.wait())
                ready_wait = asyncio.create_task(edge.connected.wait())
                waiters = [stop_wait, end_wait, ready_wait]
                done, _ = await asyncio.wait(
                    waiters, timeout=120, return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    raise RuntimeError("等待浏览器授权超时，请重新开始训练")
                if stop_wait in done or end_wait in done:
                    if edge.failure:
                        raise RuntimeError(edge.failure)
                    return
                self.ui.set_state("running", f"{settings.exercise} · {settings.target_reps} 次")
                LOGGER.info("训练已开始：浏览器全双工 AEC，请保持全身位于画面内。")
                await asyncio.wait([stop_wait, end_wait], return_when=asyncio.FIRST_COMPLETED)
                if edge.failure:
                    raise RuntimeError(edge.failure)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("训练启动失败")
            self.ui.set_state("error", "启动失败")
            self.ui.append_log(str(exc), "error")
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            if agent is not None:
                with contextlib.suppress(Exception):
                    await agent.close()
            elif processor is not None:
                with contextlib.suppress(Exception):
                    await processor.close()
            if edge is not None:
                with contextlib.suppress(Exception):
                    await edge.close()
            if self.ui.alive and self.ui.state != "error":
                self.ui.set_state("idle", "待命")
                LOGGER.info("训练已停止。")
