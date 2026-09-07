import AVFoundation
import Foundation

private enum WireType: UInt8 {
    case playback = 0x50 // P: Python -> Swift PCM16 mono @ 48 kHz
    case flush = 0x46    // F
    case stop = 0x53     // S

    case mic = 0x4D      // M: Swift -> Python PCM16 mono @ negotiated input rate
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

private func describe(_ format: AVAudioFormat) -> String {
    return "\(Int(format.sampleRate))Hz/\(format.channelCount)ch/\(format.commonFormat.rawValue)"
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
        guard let part = try? stdinHandle.read(upToCount: remaining), !part.isEmpty else {
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
    private let playbackSampleRate: Double = 48_000
    private let playbackChannels: AVAudioChannelCount = 1
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var playbackFormat: AVAudioFormat!
    private var warmupUntil = DispatchTime.now()
    private var readySent = false

    func start() throws {
        playbackFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: playbackSampleRate,
            channels: playbackChannels,
            interleaved: false
        )

        guard playbackFormat != nil else {
            throw NSError(
                domain: "VisionCoachAEC",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Failed to create 48 kHz mono playback format"]
            )
        }

        let inputNode = engine.inputNode
        let outputNode = engine.outputNode

        let inputBefore = inputNode.outputFormat(forBus: 0)
        let outputBefore = outputNode.inputFormat(forBus: 0)
        log("before VPIO input=\(describe(inputBefore)) output=\(describe(outputBefore))")

        engine.attach(player)

        // Apple requires the engine to be stopped while switching the I/O
        // nodes into voice-processing mode. Enabling either I/O node causes
        // AVAudioEngine to switch both sides to VoiceProcessingIO.
        engine.stop()
        try inputNode.setVoiceProcessingEnabled(true)

        guard inputNode.isVoiceProcessingEnabled,
              outputNode.isVoiceProcessingEnabled else {
            throw NSError(
                domain: "VisionCoachAEC",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Voice processing did not become active on both I/O nodes"]
            )
        }

        let inputAfter = inputNode.outputFormat(forBus: 0)
        let outputAfter = outputNode.inputFormat(forBus: 0)
        log("after VPIO input=\(describe(inputAfter)) output=\(describe(outputAfter))")

        // Keep Qwen playback at the stable 48 kHz mono contract. The main
        // mixer is responsible for conversion to the active Core Audio route.
        engine.connect(player, to: engine.mainMixerNode, format: playbackFormat)

        // IMPORTANT: do not force the microphone tap to 48 kHz mono.
        // VoiceProcessingIO negotiates an aggregate/client format on macOS.
        // Supplying an explicit incompatible tap format can make output-node
        // initialization fail with kAudioUnitErr_FailedInitialization (-10875).
        inputNode.installTap(
            onBus: 0,
            bufferSize: 960,
            format: nil
        ) { [weak self] buffer, _ in
            self?.emitMic(buffer)
        }

        engine.prepare()
        try engine.start()
        player.play()

        warmupUntil = DispatchTime.now() + .milliseconds(350)
        scheduleSilence(milliseconds: 350)

        log("VoiceProcessingIO engine started; waiting for first microphone buffer")
    }

    private func scheduleSilence(milliseconds: Int) {
        let frames = Int(playbackSampleRate * Double(milliseconds) / 1000.0)
        let data = Data(count: frames * MemoryLayout<Int16>.size)
        schedulePlayback(data)
    }

    private func emitReadyIfNeeded(_ buffer: AVAudioPCMBuffer) {
        guard !readySent else { return }
        readySent = true

        let sampleRate = Int(buffer.format.sampleRate.rounded())
        let payload = """
        {"sample_rate":\(sampleRate),"channels":1,"voice_processing":true}
        """.data(using: .utf8) ?? Data()

        writeFrame(.ready, payload: payload)
        log("VoiceProcessingIO active: capture=\(sampleRate)Hz/1ch playback=48000Hz/1ch")
    }

    private func emitMic(_ buffer: AVAudioPCMBuffer) {
        emitReadyIfNeeded(buffer)

        if DispatchTime.now() < warmupUntil {
            return
        }

        guard let channelData = buffer.floatChannelData else { return }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return }

        // Voice capture sent to Python is intentionally mono. For a
        // multi-channel negotiated input, use the first VPIO-processed channel
        // rather than forcing the tap itself to a mono format.
        let src = channelData[0]
        var payload = Data(count: frameCount * MemoryLayout<Int16>.size)
        payload.withUnsafeMutableBytes { raw in
            guard let dst = raw.bindMemory(to: Int16.self).baseAddress else { return }
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

        guard let channelData = buffer.floatChannelData else { return }
        let dst = channelData[0]
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
    let nsError = error as NSError
    var message = String(describing: error)

    if nsError.code == -10875 {
        message += """
        
        HINT: Core Audio returned kAudioUnitErr_FailedInitialization (-10875).
        On macOS VoiceProcessingIO this commonly occurs when the current system
        input/output routes cannot form a compatible voice-processing pair.
        First test with System Settings > Sound using the built-in MacBook
        microphone AND built-in MacBook speakers, then restart this helper.
        """
    }

    let payload = message.data(using: .utf8) ?? Data()
    writeFrame(.error, payload: payload)
    log("startup failed: \(message)")
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
