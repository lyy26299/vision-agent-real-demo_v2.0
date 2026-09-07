"""Full-duplex WebRTC Audio Processing Module backend.

This backend keeps PortAudio/sounddevice for hardware I/O and inserts WebRTC
APM (AEC3 + high-pass filter) immediately next to the duplex callback.

The exact samples written to the speaker are also fed into the reverse/render
stream before microphone capture is processed. Capture and render therefore
share one 10 ms hardware callback and one time base.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import platform
import queue
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd


LOGGER = logging.getLogger("vision_coach.webrtc_apm")

_SAMPLE_RATE = 48_000
_CHANNELS = 1
_FRAME_MS = 10
_FRAME_SAMPLES = _SAMPLE_RATE * _FRAME_MS // 1000


class WebRTCAPMUnavailable(RuntimeError):
    """Raised when the bundled WebRTC APM bridge cannot be built or loaded."""


@dataclass
class AudioMetrics:
    callbacks: int = 0
    input_overflows: int = 0
    output_underflows: int = 0
    capture_drops: int = 0
    render_errors: int = 0
    capture_errors: int = 0
    delay_ms: float = -1.0


class _SampleFIFO:
    def __init__(self) -> None:
        self._chunks: deque[np.ndarray] = deque()
        self._offset = 0
        self._lock = threading.Lock()

    def append(self, samples: np.ndarray) -> None:
        data = np.asarray(samples, dtype=np.int16).reshape(-1).copy()
        if not data.size:
            return
        with self._lock:
            self._chunks.append(data)

    def pop_exact(self, count: int) -> np.ndarray:
        output = np.zeros(count, dtype=np.int16)
        written = 0

        with self._lock:
            while written < count and self._chunks:
                current = self._chunks[0]
                available = current.size - self._offset
                take = min(count - written, available)
                output[written : written + take] = current[
                    self._offset : self._offset + take
                ]
                written += take
                self._offset += take

                if self._offset >= current.size:
                    self._chunks.popleft()
                    self._offset = 0

        return output

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._offset = 0


class WebRTCAPM:
    """ctypes wrapper around the small Rust/C ABI bridge."""

    def __init__(self, sample_rate: int = _SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.frame_samples = sample_rate // 100
        self._lib = self._load_library()
        self._configure_abi()

        self._handle = self._lib.vc_apm_create(sample_rate)
        if not self._handle:
            raise WebRTCAPMUnavailable("WebRTC APM 创建失败")

        native_frame_samples = int(self._lib.vc_apm_frame_samples(self._handle))
        if native_frame_samples != self.frame_samples:
            self.close()
            raise WebRTCAPMUnavailable(
                f"WebRTC APM 帧长不匹配：native={native_frame_samples}, "
                f"python={self.frame_samples}"
            )

    @classmethod
    def prepare(cls) -> Path:
        return cls._ensure_native_library()

    def process_render(self, samples: np.ndarray) -> None:
        frame = np.ascontiguousarray(samples, dtype=np.int16).reshape(-1)
        if frame.size != self.frame_samples:
            raise ValueError(
                f"render 必须是 {self.frame_samples} samples / 10 ms"
            )

        code = self._lib.vc_apm_process_render(
            self._handle,
            frame.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            frame.size,
        )
        if code != 0:
            raise RuntimeError(f"WebRTC ProcessReverseStream 失败：{code}")

    def process_capture(
        self,
        samples: np.ndarray,
        *,
        delay_ms: int = -1,
    ) -> np.ndarray:
        source = np.ascontiguousarray(samples, dtype=np.int16).reshape(-1)
        if source.size != self.frame_samples:
            raise ValueError(
                f"capture 必须是 {self.frame_samples} samples / 10 ms"
            )

        output = np.empty_like(source)
        code = self._lib.vc_apm_process_capture(
            self._handle,
            source.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            output.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            source.size,
            int(delay_ms),
        )
        if code != 0:
            raise RuntimeError(f"WebRTC ProcessStream 失败：{code}")
        return output

    def reset(self) -> None:
        if self._handle:
            self._lib.vc_apm_reset(self._handle)

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._lib.vc_apm_destroy(self._handle)
            self._handle = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _configure_abi(self) -> None:
        self._lib.vc_apm_create.argtypes = [ctypes.c_uint32]
        self._lib.vc_apm_create.restype = ctypes.c_void_p

        self._lib.vc_apm_frame_samples.argtypes = [ctypes.c_void_p]
        self._lib.vc_apm_frame_samples.restype = ctypes.c_size_t

        self._lib.vc_apm_process_render.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_size_t,
        ]
        self._lib.vc_apm_process_render.restype = ctypes.c_int32

        self._lib.vc_apm_process_capture.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_size_t,
            ctypes.c_int32,
        ]
        self._lib.vc_apm_process_capture.restype = ctypes.c_int32

        self._lib.vc_apm_reset.argtypes = [ctypes.c_void_p]
        self._lib.vc_apm_reset.restype = None

        self._lib.vc_apm_destroy.argtypes = [ctypes.c_void_p]
        self._lib.vc_apm_destroy.restype = None

    @classmethod
    def _load_library(cls) -> ctypes.CDLL:
        path = cls._ensure_native_library()
        try:
            return ctypes.CDLL(str(path))
        except OSError as exc:
            raise WebRTCAPMUnavailable(
                f"无法加载 WebRTC APM 动态库：{path}\n{exc}"
            ) from exc

    @classmethod
    def _ensure_native_library(cls) -> Path:
        cargo = shutil.which("cargo")
        if cargo is None:
            raise WebRTCAPMUnavailable(
                "未找到 cargo。WebRTC APM bundled bridge 需要 Rust toolchain。"
            )

        missing = [
            command
            for command in ("pkg-config", "meson", "ninja", "clang")
            if shutil.which(command) is None
        ]
        if missing:
            raise WebRTCAPMUnavailable(
                "缺少 WebRTC APM 构建工具：" + ", ".join(missing)
            )

        project_root = Path(__file__).resolve().parents[1]
        manifest = project_root / "native" / "webrtc_apm_bridge" / "Cargo.toml"
        source = project_root / "native" / "webrtc_apm_bridge" / "src" / "lib.rs"
        if not manifest.exists() or not source.exists():
            raise WebRTCAPMUnavailable("缺少 native/webrtc_apm_bridge 源码")

        cache_root = Path(
            os.getenv(
                "VISION_COACH_WEBRTC_APM_CACHE",
                Path.home() / "Library" / "Caches" / "VisionCoach" / "webrtc_apm",
            )
        )
        target_dir = cache_root / "target"

        if platform.system() == "Darwin":
            library = target_dir / "release" / "libvisioncoach_webrtc_apm.dylib"
        elif platform.system() == "Windows":
            library = target_dir / "release" / "visioncoach_webrtc_apm.dll"
        else:
            library = target_dir / "release" / "libvisioncoach_webrtc_apm.so"

        newest_source = max(
            manifest.stat().st_mtime_ns,
            source.stat().st_mtime_ns,
        )
        if library.exists() and library.stat().st_mtime_ns >= newest_source:
            return library

        cache_root.mkdir(parents=True, exist_ok=True)
        LOGGER.info("首次启动：正在构建 bundled WebRTC APM / AEC3 bridge...")

        env = os.environ.copy()
        env["CARGO_TARGET_DIR"] = str(target_dir)

        result = subprocess.run(
            [
                cargo,
                "build",
                "--release",
                "--manifest-path",
                str(manifest),
            ],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise WebRTCAPMUnavailable(
                "WebRTC APM bridge 构建失败。\n"
                + (detail or "cargo build returned non-zero status")
            )

        if not library.exists():
            raise WebRTCAPMUnavailable(
                f"cargo 构建成功但未找到动态库：{library}"
            )

        return library


class WebRTCDuplexBackend:
    """One full-duplex PortAudio stream plus one WebRTC APM instance."""

    def __init__(
        self,
        audio_input: Any,
        audio_output: Any,
        *,
        sample_rate: int = _SAMPLE_RATE,
    ) -> None:
        self.input_index = int(audio_input.index)
        self.output_index = int(audio_output.index)
        self.input_name = str(audio_input.name)
        self.output_name = str(audio_output.name)

        self.sample_rate = sample_rate
        self.channels = _CHANNELS
        self.blocksize = sample_rate // 100

        self.apm = WebRTCAPM(sample_rate)
        self.metrics = AudioMetrics()

        self._playout = _SampleFIFO()
        self._capture: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stream: sd.RawStream | None = None
        self._clients: set[str] = set()
        self._state_lock = threading.Lock()
        self._delay_ema_ms: float | None = None

    @property
    def name(self) -> str:
        return f"WebRTC APM: {self.input_name} ↔ {self.output_name}"

    def start_client(self, client: str) -> None:
        with self._state_lock:
            self._clients.add(client)
            if self._stream is not None:
                return
            self._start_stream()

    def stop_client(self, client: str) -> None:
        with self._state_lock:
            self._clients.discard(client)
            if self._clients:
                return
            self._stop_stream()

    def write(self, samples: np.ndarray) -> None:
        self._playout.append(samples)

    def flush(self) -> None:
        # Do not reset AEC3: keep the learned acoustic echo path.
        self._playout.clear()

    def read(self, timeout: float = 0.1) -> np.ndarray | None:
        try:
            return self._capture.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        with self._state_lock:
            self._clients.clear()
            self._stop_stream()
        self.apm.close()

    def _start_stream(self) -> None:
        self._drain_capture()
        self._playout.clear()
        self._delay_ema_ms = None

        self._stream = sd.RawStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            device=(self.input_index, self.output_index),
            channels=(1, 1),
            dtype="int16",
            latency="low",
            callback=self._callback,
        )
        self._stream.start()
        LOGGER.info(
            "WebRTC APM duplex ready: %s -> %s, %d Hz, %d samples/10ms",
            self.input_name,
            self.output_name,
            self.sample_rate,
            self.blocksize,
        )

    def _stop_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        self._playout.clear()
        self._drain_capture()

    def _callback(
        self,
        indata: Any,
        outdata: Any,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        self.metrics.callbacks += 1

        if status.input_overflow:
            self.metrics.input_overflows += 1
        if status.output_underflow:
            self.metrics.output_underflows += 1

        out_view = np.frombuffer(outdata, dtype=np.int16, count=frames)
        if frames != self.blocksize:
            out_view[:] = 0
            return

        render = self._playout.pop_exact(frames)
        out_view[:] = render

        try:
            self.apm.process_render(render)
        except Exception:
            self.metrics.render_errors += 1

        capture = np.frombuffer(indata, dtype=np.int16, count=frames).copy()
        delay_ms = self._estimate_delay_ms(time_info)

        try:
            clean = self.apm.process_capture(capture, delay_ms=delay_ms)
        except Exception:
            self.metrics.capture_errors += 1
            clean = capture

        block = clean.reshape(-1, 1)
        try:
            self._capture.put_nowait(block)
        except queue.Full:
            self.metrics.capture_drops += 1
            try:
                self._capture.get_nowait()
            except queue.Empty:
                pass
            try:
                self._capture.put_nowait(block)
            except queue.Full:
                pass

    def _estimate_delay_ms(self, time_info: Any) -> int:
        try:
            adc = float(time_info.inputBufferAdcTime)
            dac = float(time_info.outputBufferDacTime)
            raw_ms = (dac - adc) * 1000.0
        except (AttributeError, TypeError, ValueError):
            raw_ms = math.nan

        if not math.isfinite(raw_ms) or raw_ms < 0.0 or raw_ms > 500.0:
            self.metrics.delay_ms = -1.0
            return -1

        if self._delay_ema_ms is None:
            self._delay_ema_ms = raw_ms
        else:
            self._delay_ema_ms = 0.9 * self._delay_ema_ms + 0.1 * raw_ms

        self.metrics.delay_ms = self._delay_ema_ms
        return int(round(self._delay_ema_ms))

    def _drain_capture(self) -> None:
        while True:
            try:
                self._capture.get_nowait()
            except queue.Empty:
                return


class APMInputDevice:
    def __init__(self, backend: WebRTCDuplexBackend) -> None:
        self.backend = backend
        self.index = backend.input_index
        self.name = f"{backend.input_name} · WebRTC AEC3"
        self.is_default = True

    @property
    def sample_rate(self) -> int:
        return self.backend.sample_rate

    @property
    def channels(self) -> int:
        return self.backend.channels

    def start(self) -> None:
        self.backend.start_client("input")

    def read(self) -> np.ndarray | None:
        return self.backend.read()

    def stop(self) -> None:
        self.backend.stop_client("input")


class APMOutputDevice:
    def __init__(self, backend: WebRTCDuplexBackend) -> None:
        self.backend = backend
        self.index = backend.output_index
        self.name = f"{backend.output_name} · WebRTC AEC3 Reference"
        self.is_default = True

    @property
    def sample_rate(self) -> int:
        return self.backend.sample_rate

    @property
    def channels(self) -> int:
        return self.backend.channels

    def start(self) -> None:
        self.backend.start_client("output")

    def write(self, samples: np.ndarray) -> None:
        self.backend.write(samples)

    def flush(self) -> None:
        self.backend.flush()

    def stop(self) -> None:
        self.backend.stop_client("output")


def prepare_webrtc_apm() -> Path:
    return WebRTCAPM.prepare()


def make_webrtc_apm_devices(
    audio_input: Any,
    audio_output: Any,
) -> tuple[APMInputDevice, APMOutputDevice]:
    backend = WebRTCDuplexBackend(audio_input, audio_output)
    return APMInputDevice(backend), APMOutputDevice(backend)
