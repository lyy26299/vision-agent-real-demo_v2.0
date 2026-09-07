# macOS Full-Duplex AEC Mode

## 1. Why this mode exists

The legacy local mode uses two independent PortAudio/sounddevice streams:

- microphone capture;
- speaker playback.

That is simple, but the operating system does not see the agent playback as the
reference signal of a voice-processing input/output graph. Acoustic playback can
therefore leak back into the microphone and be transcribed as if the user spoke.

The new default macOS entry point keeps the original UI and Agent lifecycle but
replaces only the local audio backend.

## 2. Architecture

~~~text
Qwen audio
    ↓
Vision Agents AudioOutputStream
    ↓
LocalOutputAudioTrack
    ↓ PCM16 48 kHz mono
AECOutputDevice
    ↓
native/macos_aec_bridge.swift
    ↓
AVAudioPlayerNode
    ↓
AVAudioEngine / VoiceProcessingIO
    ↓
macOS speaker
          │
          │ AEC reference
          ▼
macOS microphone
    ↓
AVAudioEngine / VoiceProcessingIO
    ↓ echo-cancelled PCM16 48 kHz mono
AECInputDevice
    ↓
LocalEdge AudioReceivedEvent
    ↓
Qwen Realtime
~~~

Apple documents AVAudioEngine voice-processing mode as the mode intended for
VoIP / echo-cancellation use. Enabling voice processing on an I/O node places
the engine's I/O path into voice-processing mode, allowing device playback to be
removed from the microphone signal.

References:

- https://developer.apple.com/documentation/avfaudio/avaudioionode/setvoiceprocessingenabled(_:)
- https://developer.apple.com/videos/play/wwdc2019/510/
- https://developer.apple.com/documentation/audiotoolbox/kaudiounitsubtype_voiceprocessingio

## 3. Files

~~~text
agent_local.py
    New macOS AEC entry point.

agent_local_legacy.py
    Original sounddevice implementation, preserved unchanged.

coach/macos_aec.py
    LocalEdge-compatible Python input/output devices and IPC management.

native/macos_aec_bridge.swift
    Native AVAudioEngine VoiceProcessingIO process.

scripts/check_macos_aec.py
    AEC compile/start/microphone smoke test.
~~~

The existing agent_local_agent.py is intentionally unchanged.

## 4. Why a native Swift helper is used

Do not run the Core Audio realtime render callback through Python if it can be
avoided.

The Swift helper owns:

- AVAudioEngine;
- AVAudioInputNode;
- AVAudioOutputNode;
- AVAudioPlayerNode;
- voice-processing enablement;
- microphone tap;
- playback scheduling.

Python owns only:

- framed PCM transport;
- LocalEdge compatibility;
- queueing;
- Agent lifecycle.

This keeps the latency-sensitive Apple audio graph native and keeps the Python
GIL / garbage collector out of the audio render callback.

## 5. Audio route rule

AEC mode intentionally exposes only one logical input and one logical output:

~~~text
系统默认麦克风 · Apple AEC
系统默认扬声器 · Apple AEC Reference
~~~

They are not two independently selectable PortAudio devices. Both represent the
same AVAudioEngine I/O graph.

To change microphone or speaker, change the current macOS system audio route.
Independent input/output routing should not be added to the first AEC version
unless the native Core Audio route is explicitly reconfigured and tested.

## 6. First run

The native helper is source code and is compiled locally on first use.

Requirement:

~~~bash
xcode-select -p
swiftc --version
~~~

If swiftc is unavailable, install Apple's Command Line Tools first.

The compiled helper is cached outside the repository at:

~~~text
~/Library/Caches/VisionCoach/macos_aec_bridge
~~~

It is automatically rebuilt when native/macos_aec_bridge.swift changes.

## 7. Smoke test

Before launching the full Agent:

~~~bash
uv run python scripts/check_macos_aec.py
~~~

Expected result:

~~~text
AEC_READY {'sample_rate': 48000, 'channels': 1, 'voice_processing': True}
MIC_OK chunks=... samples=...
~~~

macOS may request microphone permission the first time.

## 8. Launch

New default AEC mode:

~~~bash
uv run python agent_local.py
~~~

Old mode for A/B comparison:

~~~bash
uv run python agent_local_legacy.py
~~~

## 9. How to validate actual AEC

Do not validate AEC only by checking that the agent stops talking when the user
speaks. That tests interruption/VAD, not acoustic echo cancellation.

Use the same room, speaker volume, microphone position, prompt, and Qwen voice
for both modes.

### Legacy test

~~~bash
uv run python agent_local_legacy.py
~~~

Let the agent speak while the built-in speaker is audible. Observe whether the
agent's own speech appears in user transcription or triggers another response.

### AEC test

~~~bash
uv run python agent_local.py
~~~

Repeat the exact same test.

Success criteria for the first version:

1. agent playback no longer repeatedly appears as user speech;
2. the user can speak while agent audio is playing;
3. user speech remains intelligible during overlap;
4. interruption still clears pending agent audio;
5. no repeated feedback loop such as agent -> microphone -> agent.

## 10. Warm-up

The bridge feeds 350 ms of silence through the playback graph and discards input
during this period.

Reason: a voice-processing echo canceller requires a short convergence period.
This is not a mute-while-speaking strategy; after warm-up the microphone remains
open during playback.

## 11. What this does not guarantee

VoiceProcessingIO materially improves the audio architecture, but it cannot
guarantee zero residual echo in every physical setup.

Results can still depend on:

- macOS version;
- active hardware route;
- built-in vs external speaker/microphone;
- room acoustics;
- extreme speaker volume;
- route changes during a session;
- Bluetooth device behavior.

If a headset route already provides hardware echo isolation, the benefit may be
small. If the route changes while training, restart the session so the audio
graph can be rebuilt.

## 12. Next engineering checks

After the first real Mac test, record:

- AEC startup success/failure;
- microphone chunk cadence;
- user barge-in latency;
- number of self-transcription events in a fixed 5-minute script;
- number of false user-turn starts during agent-only speech.

If residual echo remains severe, inspect the actual selected Core Audio route
before changing Qwen/VAD thresholds. The first debugging question is whether the
speaker signal is still traveling through the same AVAudioEngine graph that
owns the microphone.
