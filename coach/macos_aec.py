"""macOS full-duplex audio backend using AVAudioEngine VoiceProcessingIO.

The realtime audio callback stays in a small native Swift helper. Python only
exchanges PCM frames with that helper, so Apple owns the microphone/speaker
graph and can use the speaker render signal as the AEC reference.

This module intentionally exposes the tiny interface expected by
vision-agents' LocalEdge AudioInputDevice / AudioOutputDevice.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import shutil
import struct
import subprocess
import threading
from pathlib import Path
from typing import BinaryIO

import numpy as np


LOGGER = logging.getLogger("vision_coach.aec")

_SAMPLE_RATE = 48_000
_CHANNELS = 1

_PLAYBACK = b"P"
_FLUSH = b"F"
_STOP = b"S"
_MIC = b"M"
_READY = b"R"
_ERROR = b"E"


class MacOSAECUnavailable(RuntimeError):
    """Raised when the native macOS VoiceProcessingIO backend cannot start."""


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _pack_frame(kind: bytes, payload: bytes = b"") -> bytes:
    if len(kind) != 1:
        raise ValueError("wire frame type must be exactly one byte")
    return kind + struct.pack("<I", len(payload)) + payload


class MacOSVoiceProcessingBackend:
    """Shared microphone + speaker engine backed by Apple's VoiceProcessingIO."""

    def __init__(
        self,
        *,
        sample_rate: int = _SAMPLE_RATE,
        channels: int = _CHANNELS,
        startup_timeout_s: float = 8.0,
    ) -> None:
        if platform.system() != "Darwin":
            raise MacOSAECUnavailable("Apple VoiceProcessingIO mode only supports macOS")
        if sample_rate != _SAMPLE_RATE or channels != _CHANNELS:
            raise ValueError("current native bridge contract is fixed at 48 kHz mono")

        self.sample_rate = sample_rate
        self.channels = channels
        self.startup_timeout_s = startup_timeout_s

        self._process: subprocess.Popen[bytes] | None = None
        self._mic_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=80)
        self._wire_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._ready = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._clients: set[str] = set()
        self._startup_error: str | None = None
        self._status: dict[str, object] = {}

    @property
    def name(self) -> str:
        return "Apple VoiceProcessingIO / AVAudioEngine (AEC)"

    def prepare(self) -> Path:
        """Compile/cache the native helper without opening microphone audio."""
        return self._ensure_native_bridge()

    @property
    def status(self) -> dict[str, object]:
        return dict(self._status)

    def start_client(self, client: str) -> None:
        with self._state_lock:
            self._clients.add(client)
            if self._process is not None and self._process.poll() is None:
                return
            self._start_process_locked()

    def stop_client(self, client: str) -> None:
        with self._state_lock:
            self._clients.discard(client)
            if self._clients:
                return
            self._stop_process_locked()

    def read(self, timeout: float = 0.1) -> np.ndarray | None:
        try:
            return self._mic_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def write(self, samples: np.ndarray) -> None:
        process = self._require_process()
        mono = np.asarray(samples, dtype=np.int16).reshape(-1)
        self._send(process, _PLAYBACK, mono.astype("<i2", copy=False).tobytes())

    def flush(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        self._send(process, _FLUSH)

    def close(self) -> None:
        with self._state_lock:
            self._clients.clear()
            self._stop_process_locked()

    def _start_process_locked(self) -> None:
        binary = self._ensure_native_bridge()

        self._ready.clear()
        self._startup_error = None
        self._status = {}

        self._process = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="macos-aec-reader",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop,
            name="macos-aec-stderr",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread.start()

        if not self._ready.wait(self.startup_timeout_s):
            error = self._startup_error or "native VoiceProcessingIO helper did not become ready"
            self._stop_process_locked(force=True)
            raise MacOSAECUnavailable(error)

        if self._startup_error:
            error = self._startup_error
            self._stop_process_locked(force=True)
            raise MacOSAECUnavailable(error)

        LOGGER.info(
            "Apple VoiceProcessingIO ready: %s Hz, %s channel(s)",
            self._status.get("sample_rate", self.sample_rate),
            self._status.get("channels", self.channels),
        )

    def _stop_process_locked(self, *, force: bool = False) -> None:
        process = self._process
        if process is None:
            return

        if process.poll() is None and not force:
            try:
                self._send(process, _STOP)
                process.wait(timeout=2)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                force = True

        if force and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

        self._process = None
        self._ready.clear()
        self._drain_mic_queue()

    def _require_process(self) -> subprocess.Popen[bytes]:
        process = self._process
        if process is None or process.poll() is not None:
            raise MacOSAECUnavailable("VoiceProcessingIO backend is not running")
        return process

    def _send(
        self,
        process: subprocess.Popen[bytes],
        kind: bytes,
        payload: bytes = b"",
    ) -> None:
        if process.stdin is None:
            raise MacOSAECUnavailable("VoiceProcessingIO stdin pipe is unavailable")
        frame = _pack_frame(kind, payload)
        with self._wire_lock:
            process.stdin.write(frame)
            process.stdin.flush()

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        try:
            while True:
                header = _read_exact(process.stdout, 5)
                if header is None:
                    break
                kind = header[:1]
                (length,) = struct.unpack("<I", header[1:])
                payload = _read_exact(process.stdout, length) if length else b""
                if payload is None:
                    break

                if kind == _MIC:
                    samples = np.frombuffer(payload, dtype="<i2").copy().reshape(-1, 1)
                    while self._mic_queue.full():
                        try:
                            self._mic_queue.get_nowait()
                        except queue.Empty:
                            break
                    try:
                        self._mic_queue.put_nowait(samples)
                    except queue.Full:
                        pass
                elif kind == _READY:
                    try:
                        self._status = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._status = {
                            "sample_rate": self.sample_rate,
                            "channels": self.channels,
                            "voice_processing": True,
                        }

                    # The native VPIO capture side is allowed to negotiate its
                    # actual macOS sample rate. LocalEdge reads these properties
                    # when wrapping each microphone block into PcmData, and the
                    # Qwen adapter already resamples PcmData to its required
                    # 16 kHz input rate.
                    negotiated_rate = self._status.get("sample_rate")
                    negotiated_channels = self._status.get("channels")
                    if isinstance(negotiated_rate, (int, float)) and negotiated_rate > 0:
                        self.sample_rate = int(negotiated_rate)
                    if isinstance(negotiated_channels, int) and negotiated_channels > 0:
                        self.channels = negotiated_channels

                    self._ready.set()
                elif kind == _ERROR:
                    self._startup_error = payload.decode("utf-8", errors="replace")
                    self._ready.set()
                    LOGGER.error("VoiceProcessingIO helper error: %s", self._startup_error)
        except Exception:
            LOGGER.exception("VoiceProcessingIO IPC reader failed")
        finally:
            if not self._ready.is_set() and process.poll() is not None:
                self._startup_error = (
                    self._startup_error
                    or f"VoiceProcessingIO helper exited with code {process.returncode}"
                )
                self._ready.set()

    def _stderr_loop(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw_line in iter(process.stderr.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                LOGGER.info("%s", line)

    def _ensure_native_bridge(self) -> Path:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            raise MacOSAECUnavailable(
                "未找到 swiftc。请先安装 Apple Command Line Tools，然后重新启动 AEC 模式。"
            )

        project_root = Path(__file__).resolve().parents[1]
        source = project_root / "native" / "macos_aec_bridge.swift"
        if not source.exists():
            raise MacOSAECUnavailable(f"缺少原生 AEC 源码：{source}")

        cache_root = Path(
            os.getenv(
                "VISION_COACH_AEC_CACHE",
                Path.home() / "Library" / "Caches" / "VisionCoach",
            )
        )
        cache_root.mkdir(parents=True, exist_ok=True)
        binary = cache_root / "macos_aec_bridge"

        needs_build = (
            not binary.exists()
            or binary.stat().st_mtime_ns < source.stat().st_mtime_ns
        )
        if not needs_build:
            return binary

        LOGGER.info("首次启动 AEC：正在编译原生 AVAudioEngine bridge...")
        result = subprocess.run(
            [swiftc, "-O", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise MacOSAECUnavailable(
                "原生 AEC bridge 编译失败。\n" + (detail or "swiftc returned a non-zero status")
            )

        binary.chmod(0o755)
        return binary

    def _drain_mic_queue(self) -> None:
        while True:
            try:
                self._mic_queue.get_nowait()
            except queue.Empty:
                return


class AECInputDevice:
    """LocalEdge-compatible microphone device backed by the shared AEC graph."""

    def __init__(self, backend: MacOSVoiceProcessingBackend) -> None:
        self.backend = backend
        self.index = 0
        self.name = "系统默认麦克风 · Apple AEC"
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


class AECOutputDevice:
    """LocalEdge-compatible speaker device sharing the same AEC render graph."""

    def __init__(self, backend: MacOSVoiceProcessingBackend) -> None:
        self.backend = backend
        self.index = 0
        self.name = "系统默认扬声器 · Apple AEC Reference"
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


def make_aec_devices() -> tuple[AECInputDevice, AECOutputDevice]:
    backend = MacOSVoiceProcessingBackend()
    return AECInputDevice(backend), AECOutputDevice(backend)
