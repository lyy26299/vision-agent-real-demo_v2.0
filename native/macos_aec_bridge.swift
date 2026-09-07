import AVFoundation
import Foundation

private enum WireType: UInt8 {
    case playback = 0x50 // P: Python -> Swift PCM16 mono @ 48 kHz
    case flush = 0x46    // F
    case stop = 0x53     // S

    case mic = 0x4D      // M: Swift -> Python PCM16 mono @ 48 kHz
    case ready = 0x52    // R
    case error = 0x45    // E
}

private let stdinHandle = FileHandle.standardInput
private let stdoutHandle = FileHandle.standardOutput
private let stderrHandle = FileHandle.standardError
private let wireQueue = DispatchQueue(label: "vision.coach.aec.wire")
private let audioControlQueue = DispatchQueue(label: "vision.coach.aec.control")

private func log(_ message: String) {
    guard let data = ("[macos-aec] " + message + "\n").data(using: .utf8) else { return }
    stderrHandle.write(data)
}

private func writeFrame(_ type: WireType, payload: Data = Data()) {
    var length = UInt32(payload.count).littleEndian
    var frame = Data([type.rawValue])
    withUnsafeBytes(of: &length) { frame.append(contentsOf: $0) }
    frame.append(payload)

    wireQueue.async {
        stdoutHandle.write(frame)
    }
}

private func readExactly(_ count: Int) -> Data? {
    var output = Data()
    while output.count < count {
        let remaining = count - output.count
        guard let part = try? stdinHandle.read(upToCount: remaining), let part, !part.isEmpty else {
            return nil
        }
        output.append(part)
    }
    return output
}

private func readCommand() -> (WireType, Data)? {
    guard let header = readExactly(5), header.count == 5 else { return nil }
    guard let type = WireType(rawValue: header[0]) else { return nil }

    let length: UInt32 = header[1..<5].withUnsafeBytes { rawBuffer in
        rawBuffer.loadUnaligned(as: UInt32.self)
    }
    let payloadLength = Int(UInt32(littleEndian: length))
    guard payloadLength >= 0 else { return nil }
    guard payloadLength > 0 else { return (type, Data()) }
    guard let payload = readExactly(payloadLength) else { return nil }
    return (type, payload)
}

final class VoiceProcessingBridge {
    private let sampleRate: Double = 48_000
    private let channels: AVAudioChannelCount = 1
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var playbackFormat: AVAudioFormat!
    private var captureFormat: AVAudioFormat!
    private var warmupUntil = DispatchTime.now()

    func start() throws {
        playbackFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: channels,
            interleaved: false
        )
        captureFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: channels,
            interleaved: false
        )

        guard playbackFormat != nil, captureFormat != nil else {
            throw NSError(
                domain: "VisionCoachAEC",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Failed to create 48 kHz mono AVAudioFormat"]
            )
        }

        engine.attach(player)

        // Apple requires the engine to be stopped while switching I/O nodes
        // into voice-processing mode. Enabling it on one I/O node switches
        // the engine to VoiceProcessingIO; we verify both sides afterwards.
        engine.stop()
        try engine.inputNode.setVoiceProcessingEnabled(true)
        if !engine.outputNode.isVoiceProcessingEnabled {
            try engine.outputNode.setVoiceProcessingEnabled(true)
        }

        guard engine.inputNode.isVoiceProcessingEnabled,
              engine.outputNode.isVoiceProcessingEnabled else {
            throw NSError(
                domain: "VisionCoachAEC",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Voice processing did not become active on both I/O nodes"]
            )
        }

        engine.connect(player, to: engine.mainMixerNode, format: playbackFormat)

        engine.inputNode.installTap(
            onBus: 0,
            bufferSize: 960,
            format: captureFormat
        ) { [weak self] buffer, _ in
            self?.emitMic(buffer)
        }

        engine.prepare()
        try engine.start()
        player.play()

        // Voice-processing AEC needs a short convergence interval at startup.
        // Feed silence through the exact playback graph that will carry Qwen
        // audio, and discard microphone frames during the warm-up.
        warmupUntil = DispatchTime.now() + .milliseconds(350)
        scheduleSilence(milliseconds: 350)

        let ready = """
        {"sample_rate":48000,"channels":1,"voice_processing":true}
        """.data(using: .utf8) ?? Data()
        writeFrame(.ready, payload: ready)
        log("VoiceProcessingIO active: 48 kHz mono full-duplex")
    }

    private func scheduleSilence(milliseconds: Int) {
        let frames = Int(sampleRate * Double(milliseconds) / 1000.0)
        let data = Data(count: frames * MemoryLayout<Int16>.size)
        schedulePlayback(data)
    }

    private func emitMic(_ buffer: AVAudioPCMBuffer) {
        if DispatchTime.now() < warmupUntil {
            return
        }
        guard let channels = buffer.floatChannelData else { return }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return }

        var payload = Data(count: frameCount * MemoryLayout<Int16>.size)
        payload.withUnsafeMutableBytes { raw in
            guard let dst = raw.bindMemory(to: Int16.self).baseAddress else { return }
            let src = channels[0]
            for i in 0..<frameCount {
                let clipped = max(-1.0, min(1.0, src[i]))
                dst[i] = Int16(clipped * 32767.0)
            }
        }
        writeFrame(.mic, payload: payload)
    }

    func schedulePlayback(_ data: Data) {
        guard data.count >= 2 else { return }
        let sampleCount = data.count / MemoryLayout<Int16>.size
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: playbackFormat,
            frameCapacity: AVAudioFrameCount(sampleCount)
        ) else {
            return
        }
        buffer.frameLength = AVAudioFrameCount(sampleCount)

        guard let channels = buffer.floatChannelData else { return }
        let dst = channels[0]
        data.withUnsafeBytes { raw in
            let src = raw.bindMemory(to: Int16.self)
            let count = min(sampleCount, src.count)
            for i in 0..<count {
                dst[i] = Float(src[i]) / 32768.0
            }
        }

        audioControlQueue.async { [weak self] in
            guard let self else { return }
            self.player.scheduleBuffer(buffer, completionHandler: nil)
            if !self.player.isPlaying {
                self.player.play()
            }
        }
    }

    func flush() {
        audioControlQueue.sync {
            player.stop()
            player.play()
        }
    }

    func stop() {
        audioControlQueue.sync {
            player.stop()
        }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        log("VoiceProcessingIO stopped")
    }
}

let bridge = VoiceProcessingBridge()

do {
    try bridge.start()
} catch {
    let payload = String(describing: error).data(using: .utf8) ?? Data()
    writeFrame(.error, payload: payload)
    log("startup failed: \(error)")
    exit(2)
}

while let (type, payload) = readCommand() {
    switch type {
    case .playback:
        bridge.schedulePlayback(payload)
    case .flush:
        bridge.flush()
    case .stop:
        bridge.stop()
        exit(0)
    default:
        continue
    }
}

bridge.stop()
