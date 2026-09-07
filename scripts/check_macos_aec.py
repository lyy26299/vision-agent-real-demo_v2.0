"""Compile and start the native macOS AEC backend without launching Qwen."""

from __future__ import annotations

import logging
import platform
import sys
import time

from coach.macos_aec import MacOSAECUnavailable, MacOSVoiceProcessingBackend


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    if platform.system() != "Darwin":
        print("SKIP: macOS only")
        return 0

    try:
        import sounddevice as sd

        default_in, default_out = sd.default.device
        input_info = sd.query_devices(default_in)
        output_info = sd.query_devices(default_out)
        print(
            "DEFAULT_AUDIO_ROUTE",
            {
                "input": input_info.get("name"),
                "input_channels": input_info.get("max_input_channels"),
                "output": output_info.get("name"),
                "output_channels": output_info.get("max_output_channels"),
            },
        )
    except Exception as exc:
        print(f"DEFAULT_AUDIO_ROUTE unavailable: {exc}")

    backend = MacOSVoiceProcessingBackend()
    try:
        backend.start_client("smoke")
        print("AEC_READY", backend.status)
        print("Listening to echo-cancelled microphone for 2 seconds...")
        deadline = time.monotonic() + 2.0
        chunks = 0
        samples = 0
        while time.monotonic() < deadline:
            block = backend.read(timeout=0.2)
            if block is not None:
                chunks += 1
                samples += int(block.size)
        print(f"MIC_OK chunks={chunks} samples={samples}")
        return 0 if chunks > 0 else 2
    except MacOSAECUnavailable as exc:
        print(f"AEC_ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        backend.stop_client("smoke")


if __name__ == "__main__":
    raise SystemExit(main())
