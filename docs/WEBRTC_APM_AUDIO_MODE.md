# WebRTC APM Full-Duplex Audio Mode

## Status

Default local mode:

~~~bash
uv run python agent_local.py
~~~

Preserved baselines:

~~~bash
uv run python agent_local_legacy.py
uv run python agent_local_vpio.py
~~~

## Signal path

~~~text
Qwen PCM
↓
LocalOutputAudioTrack resampler
↓
APMOutputDevice
↓
playout FIFO
↓
one 48 kHz / 480-sample / 10 ms RawStream callback
├── exact speaker block → WebRTC render/reverse stream
└── exact speaker block → PortAudio output
                              │
                              │ acoustic path
                              ↓
microphone input ─────────────┘
↓
same RawStream callback
↓
WebRTC capture stream
↓
AEC3 + high-pass filter
↓
capture FIFO
↓
APMInputDevice
↓
LocalEdge
↓
Qwen Realtime
~~~

## Native bridge

The project pins:

~~~text
webrtc-audio-processing = 2.1.0
feature = bundled
~~~

The bridge is a Rust cdylib exposing a minimal C ABI. The WebRTC source is built
locally by Cargo and cached under:

~~~text
~/Library/Caches/VisionCoach/webrtc_apm/
~~~

Required build tools:

~~~text
cargo
clang
pkg-config
meson
ninja
~~~

## First check

~~~bash
uv run python scripts/check_webrtc_apm.py
~~~

This test does not open the microphone or speaker. It verifies:

1. bundled WebRTC APM can compile;
2. the native library can load;
3. 48 kHz / 10 ms frames are accepted;
4. AEC3 receives render reference and capture frames;
5. synthetic delayed echo produces finite processed output.

## Runtime invariants

- sample rate: 48 kHz;
- channels: mono;
- frame size: 480 samples;
- frame duration: 10 ms;
- render reference is the exact final PCM block written to the hardware output;
- render processing happens before capture processing inside the same callback;
- capture/output use one full-duplex RawStream;
- playback flush does not reset AEC3;
- AEC3 reset is reserved for stream/device/session reinitialization.

## Delay

The duplex callback estimates hardware delay from PortAudio timestamps:

~~~text
outputBufferDacTime - inputBufferAdcTime
~~~

The estimate is range checked and EMA-smoothed before being used as the AEC
stream-delay hint. If timestamps are invalid, AEC3 is left in adaptive-delay
mode.

## DSP rollout

Current:

~~~text
AEC3
+
high-pass filter
~~~

Not enabled yet:

~~~text
noise suppression
gain control
~~~

Add those only after AEC3 passes physical double-talk tests.

## Physical acceptance

Run the same room/speaker-volume scenario in legacy and APM modes.

Required:

- agent-only speech should not repeatedly create user turns;
- user speech remains audible while agent speech is playing;
- barge-in continues working;
- playback flush does not destroy the learned echo path;
- no repeated agent → speaker → mic → agent loop.
