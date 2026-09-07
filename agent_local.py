"""Default local desktop mode using WebRTC APM / AEC3 full-duplex audio."""

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
from dataclasses import replace

from agent_local_agent import LOGGER, SessionController
from agent_local_legacy import (
    DeviceCatalog,
    FitnessCoachUI as LegacyFitnessCoachUI,
    SessionSettings,
    UiLogHandler,
)
from coach.webrtc_apm import (
    WebRTCAPMUnavailable,
    make_webrtc_apm_devices,
    prepare_webrtc_apm,
)


class FitnessCoachUI(LegacyFitnessCoachUI):
    def __init__(self, root: tk.Tk) -> None:
        self._apm_notice_shown = False
        super().__init__(root)

    def _configure_window(self) -> None:
        super()._configure_window()
        self.root.title("Vision Coach | WebRTC APM 全双工 AEC3")

    def set_devices(self, catalog: DeviceCatalog) -> None:
        super().set_devices(catalog)
        if not self._apm_notice_shown:
            self._apm_notice_shown = True
            self.append_log(
                "音频模式：WebRTC APM / AEC3 · 48 kHz · 10 ms full-duplex。",
                "success",
            )


class WebRTCSessionController(SessionController):
    def start(self, settings: SessionSettings) -> None:
        if self.task is not None and not self.task.done():
            return
        try:
            audio_input, audio_output = make_webrtc_apm_devices(
                settings.audio_input,
                settings.audio_output,
            )
        except Exception as exc:
            self.ui.set_state("error", "WebRTC APM 初始化失败")
            self.ui.append_log(str(exc), "error")
            return

        wrapped = replace(
            settings,
            audio_input=audio_input,
            audio_output=audio_output,
        )
        super().start(wrapped)


def discover_devices() -> DeviceCatalog:
    from vision_agents.plugins.local.devices import (
        CameraDevice,
        list_audio_input_devices,
        list_audio_output_devices,
        list_cameras,
    )

    prepare_webrtc_apm()

    is_macos_without_ffmpeg = (
        platform.system() == "Darwin" and shutil.which("ffmpeg") is None
    )
    cameras = [] if is_macos_without_ffmpeg else list_cameras()
    if not cameras and platform.system() == "Darwin":
        cameras = [CameraDevice(index=0, name="系统默认摄像头", device="0")]

    return DeviceCatalog(
        audio_inputs=list_audio_input_devices(),
        audio_outputs=list_audio_output_devices(),
        cameras=cameras,
    )


async def run_desktop() -> None:
    root = tk.Tk()
    ui = FitnessCoachUI(root)
    controller = WebRTCSessionController(ui)

    handler = UiLogHandler(ui.logs)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )
    root_logger.addHandler(handler)

    ui.set_state("detecting", "正在构建 WebRTC APM 并检测设备")
    discovery_task: asyncio.Task[DeviceCatalog] | None = asyncio.create_task(
        asyncio.to_thread(discover_devices),
        name="webrtc-apm-device-discovery",
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
                    ui.set_state("error", "WebRTC APM/设备检测失败")
                    ui.append_log(f"WebRTC APM/设备检测失败：{exc}", "error")
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
                    ui.set_state("detecting", "正在重新检测 WebRTC APM 与设备")
                    discovery_task = asyncio.create_task(
                        asyncio.to_thread(discover_devices),
                        name="webrtc-apm-device-refresh",
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

    if sys.version_info < (3, 11):
        raise SystemExit("本地界面需要 Python 3.11 或更高版本")

    LOGGER.info("启动 WebRTC APM / AEC3 全双工模式")
    try:
        asyncio.run(run_desktop())
    except WebRTCAPMUnavailable as exc:
        raise SystemExit(str(exc)) from exc
    except KeyboardInterrupt:
        LOGGER.info("本地训练台已关闭")


if __name__ == "__main__":
    main()
