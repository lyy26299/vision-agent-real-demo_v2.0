"""macOS AEC desktop mode for the real-time Vision Agent fitness coach.

This is the new default local entry point on macOS. The previous sounddevice
implementation is preserved unchanged in agent_local_legacy.py.

Audio architecture:

    Qwen PCM -> LocalOutputAudioTrack -> AECOutputDevice
                                      -> native AVAudioEngine player
                                      -> speaker
                                           |
                                           | Apple VoiceProcessingIO reference
                                           v
    microphone -> AVAudioEngine VoiceProcessingIO -> AECInputDevice
                                                -> LocalEdge -> Qwen

The input and output intentionally use the current macOS system audio route.
Do not select independent PortAudio input/output devices in this mode, because
AEC requires playback and capture to live inside the same voice-processing I/O
graph.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import queue
import shutil
import sys
import tkinter as tk

from agent_local_agent import LOGGER, SessionController
from agent_local_legacy import (
    DeviceCatalog,
    FitnessCoachUI as LegacyFitnessCoachUI,
    UiLogHandler,
)
from coach.macos_aec import MacOSAECUnavailable, make_aec_devices


class FitnessCoachUI(LegacyFitnessCoachUI):
    """Legacy dashboard with explicit Apple AEC mode labeling."""

    def __init__(self, root: tk.Tk) -> None:
        self._aec_notice_shown = False
        super().__init__(root)

    def _configure_window(self) -> None:
        super()._configure_window()
        self.root.title("Vision Coach | macOS 全双工 AEC")

    def set_devices(self, catalog: DeviceCatalog) -> None:
        super().set_devices(catalog)
        if (
            not self._aec_notice_shown
            and catalog.audio_inputs
            and catalog.audio_outputs
        ):
            self._aec_notice_shown = True
            self.append_log(
                "AEC 模式：麦克风与扬声器由同一个 Apple "
                "VoiceProcessingIO/AVAudioEngine 图管理。",
                "success",
            )
            self.append_log(
                "音频使用 macOS 当前系统默认输入/输出；请在系统设置中切换音频路由。",
                "normal",
            )


def discover_devices() -> DeviceCatalog:
    """Discover camera and expose one coupled Apple AEC audio route."""

    if platform.system() != "Darwin":
        raise MacOSAECUnavailable(
            "新的 agent_local.py 仅用于 macOS Apple AEC 模式。"
            "其他系统请运行 python agent_local_legacy.py。"
        )

    if shutil.which("swiftc") is None:
        raise MacOSAECUnavailable(
            "未找到 swiftc。Apple AEC 模式需要 Xcode Command Line Tools。"
        )

    from vision_agents.plugins.local.devices import CameraDevice, list_cameras

    cameras = [] if shutil.which("ffmpeg") is None else list_cameras()
    if not cameras:
        cameras = [CameraDevice(index=0, name="系统默认摄像头", device="0")]

    audio_input, audio_output = make_aec_devices()
    audio_input.backend.prepare()
    return DeviceCatalog(
        audio_inputs=[audio_input],
        audio_outputs=[audio_output],
        cameras=cameras,
    )


async def run_desktop() -> None:
    root = tk.Tk()
    ui = FitnessCoachUI(root)
    controller = SessionController(ui)

    handler = UiLogHandler(ui.logs)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )
    root_logger.addHandler(handler)

    ui.set_state("detecting", "正在检测 Apple AEC 与摄像头")
    discovery_task: asyncio.Task[DeviceCatalog] | None = asyncio.create_task(
        asyncio.to_thread(discover_devices),
        name="aec-device-discovery",
    )

    try:
        while ui.alive:
            try:
                root.update_idletasks()
                root.update()
            except tk.TclError:
                ui.alive = False
                break

            if discovery_task is not None and discovery_task.done():
                try:
                    ui.set_devices(discovery_task.result())
                except Exception as exc:
                    ui.set_state("error", "AEC/设备检测失败")
                    ui.append_log(f"AEC/设备检测失败：{exc}", "error")
                discovery_task = None

            while True:
                try:
                    action, payload = ui.actions.get_nowait()
                except queue.Empty:
                    break

                if action == "start":
                    controller.start(payload)
                elif action == "stop":
                    controller.stop()
                elif action == "refresh" and discovery_task is None:
                    ui.set_state("detecting", "正在重新检测 Apple AEC 与摄像头")
                    discovery_task = asyncio.create_task(
                        asyncio.to_thread(discover_devices),
                        name="aec-device-refresh",
                    )
                elif action == "close":
                    ui.alive = False

            ui.update()
            await asyncio.sleep(1 / 60)
    finally:
        if discovery_task is not None:
            discovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await discovery_task

        await controller.shutdown()
        root_logger.removeHandler(handler)
        with contextlib.suppress(tk.TclError):
            root.destroy()


def main() -> None:
    logging.basicConfig(
        level=getattr(
            logging,
            os.getenv("LOG_LEVEL", "INFO").upper(),
            logging.INFO,
        ),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if sys.platform != "darwin":
        raise SystemExit(
            "Apple VoiceProcessingIO AEC 模式只支持 macOS。\n"
            "请改用：python agent_local_legacy.py"
        )
    if sys.version_info < (3, 11):
        raise SystemExit("本地界面需要 Python 3.11 或更高版本")

    LOGGER.info("启动 macOS VoiceProcessingIO 全双工 AEC 模式")
    try:
        asyncio.run(run_desktop())
    except KeyboardInterrupt:
        LOGGER.info("本地训练台已关闭")


if __name__ == "__main__":
    main()
