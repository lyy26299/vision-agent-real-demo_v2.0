"""Build/load WebRTC APM and run an offline AEC3 smoke test."""

from __future__ import annotations

import math
import sys

import numpy as np

from coach.webrtc_apm import WebRTCAPM, WebRTCAPMUnavailable


SAMPLE_RATE = 48_000
FRAME = 480
DELAY_FRAMES = 12  # 120 ms synthetic acoustic path


def rms(samples: np.ndarray) -> float:
    x = samples.astype(np.float64)
    return math.sqrt(float(np.mean(x * x)) + 1e-12)


def main() -> int:
    try:
        path = WebRTCAPM.prepare()
        print("APM_LIBRARY", path)

        apm = WebRTCAPM(SAMPLE_RATE)
        print("APM_READY", {"sample_rate": SAMPLE_RATE, "frame_samples": FRAME})

        history = [np.zeros(FRAME, dtype=np.int16) for _ in range(DELAY_FRAMES)]
        before: list[float] = []
        after: list[float] = []

        phase = 0
        for index in range(240):
            t = (np.arange(FRAME) + phase) / SAMPLE_RATE
            render = (0.30 * np.sin(2 * np.pi * 700.0 * t) * 32767.0).astype(np.int16)
            phase += FRAME

            history.append(render.copy())
            echo = history.pop(0)
            capture = (echo.astype(np.float32) * 0.65).astype(np.int16)

            apm.process_render(render)
            clean = apm.process_capture(capture, delay_ms=DELAY_FRAMES * 10)

            if index >= 100:
                before.append(rms(capture))
                after.append(rms(clean))

        before_rms = float(np.mean(before))
        after_rms = float(np.mean(after))
        reduction_db = 20.0 * math.log10((before_rms + 1e-9) / (after_rms + 1e-9))

        print(
            "AEC3_OFFLINE",
            {
                "before_rms": round(before_rms, 2),
                "after_rms": round(after_rms, 2),
                "reduction_db": round(reduction_db, 2),
            },
        )

        apm.close()
        return 0 if math.isfinite(reduction_db) else 2
    except WebRTCAPMUnavailable as exc:
        print(f"APM_ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"APM_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
