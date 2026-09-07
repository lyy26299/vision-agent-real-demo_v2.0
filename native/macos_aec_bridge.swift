import AudioToolbox
import CoreAudio
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

private func osStatusError(_ status: OSStatus, _ operation: String) -> NSError {
    NSError(
        domain: "VisionCoachVoiceProcessingIO",
        code: Int(status),
        userInfo: [
            NSLocalizedDescriptionKey: "\(operation) failed (OSStatus \(status))"
        ]
    )
}

private func check(_ status: OSStatus, _ operation: String) throws {
    guard status == noErr else {
        throw osStatusError(status, operation)
    }
}

private func monoPCM16(sampleRate: Double) -> AudioStreamBasicDescription {
    let bytesPerSample = UInt32(MemoryLayout<Int16>.size)
    return AudioStreamBasicDescription(
        mSampleRate: sampleRate,
        mFormatID: kAudioFormatLinearPCM,
        mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked,
        mBytesPerPacket: bytesPerSample,
        mFramesPerPacket: 1,
        mBytesPerFrame: bytesPerSample,
        mChannelsPerFrame: 1,
        mBitsPerChannel: 16,
        mReserved: 0
    )
}

private final class PlaybackFIFO {
    private let lock = NSLock()
    private var samples: [Int16] = []
    private var readIndex = 0

    func append(_ data: Data) {
        guard !data.isEmpty else { return }
        lock.lock()
        defer { lock.unlock() }

        data.withUnsafeBytes { raw in
            let src = raw.bindMemory(to: Int16.self)
            samples.append(contentsOf: src)
        }
    }

    func fill(_ destination: UnsafeMutablePointer<Int16>, count: Int) {
        lock.lock()
        defer { lock.unlock() }

        let available = max(0, samples.count - readIndex)
        let copied = min(available, count)

        if copied > 0 {
            for i in 0..<copied {
                destination[i] = samples[readIndex + i]
            }
            readIndex += copied
        }

        if copied < count {
            for i in copied..<count {
                destination[i] = 0
            }
        }

        if readIndex > 16_384 && readIndex * 2 > samples.count {
            samples.removeFirst(readIndex)
            readIndex = 0
        }
    }

    func clear() {
        lock.lock()
        samples.removeAll(keepingCapacity: true)
        readIndex = 0
        lock.unlock()
    }
}

private func playbackCallback(
    _ inRefCon: UnsafeMutableRawPointer,
    _ ioActionFlags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
    _ inTimeStamp: UnsafePointer<AudioTimeStamp>,
    _ inBusNumber: UInt32,
    _ inNumberFrames: UInt32,
    _ ioData: UnsafeMutablePointer<AudioBufferList>?
) -> OSStatus {
    let bridge = Unmanaged<VoiceProcessingBridge>
        .fromOpaque(inRefCon)
        .takeUnretainedValue()
    return bridge.renderPlayback(frames: inNumberFrames, ioData: ioData)
}

private func captureCallback(
    _ inRefCon: UnsafeMutableRawPointer,
    _ ioActionFlags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
    _ inTimeStamp: UnsafePointer<AudioTimeStamp>,
    _ inBusNumber: UInt32,
    _ inNumberFrames: UInt32,
    _ ioData: UnsafeMutablePointer<AudioBufferList>?
) -> OSStatus {
    let bridge = Unmanaged<VoiceProcessingBridge>
        .fromOpaque(inRefCon)
        .takeUnretainedValue()
    return bridge.capture(
        flags: ioActionFlags,
        timestamp: inTimeStamp,
        frames: inNumberFrames
    )
}

private final class VoiceProcessingBridge {
    private let sampleRate: Double = 48_000
    private let channels: UInt32 = 1
    private let maxFrames: UInt32 = 4096
    private let playback = PlaybackFIFO()

    private var audioUnit: AudioUnit?
    private var captureMemory: UnsafeMutableRawPointer?
    private var warmupUntilNanos: UInt64 = 0

    deinit {
        if let captureMemory {
            captureMemory.deallocate()
        }
    }

    func start() throws {
        var description = AudioComponentDescription(
            componentType: kAudioUnitType_Output,
            componentSubType: kAudioUnitSubType_VoiceProcessingIO,
            componentManufacturer: kAudioUnitManufacturer_Apple,
            componentFlags: 0,
            componentFlagsMask: 0
        )

        guard let component = AudioComponentFindNext(nil, &description) else {
            throw NSError(
                domain: "VisionCoachVoiceProcessingIO",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "VoiceProcessingIO AudioComponent not found"]
            )
        }

        var unit: AudioUnit?
        try check(
            AudioComponentInstanceNew(component, &unit),
            "AudioComponentInstanceNew(VoiceProcessingIO)"
        )
        guard let unit else {
            throw NSError(
                domain: "VisionCoachVoiceProcessingIO",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "VoiceProcessingIO instance is nil"]
            )
        }
        audioUnit = unit

        do {
            var enabled: UInt32 = 1

            // VPIO bus 1 receives microphone hardware input. Input is disabled
            // by default, while bus 0 provides hardware playback.
            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_EnableIO,
                    kAudioUnitScope_Input,
                    1,
                    &enabled,
                    UInt32(MemoryLayout<UInt32>.size)
                ),
                "Enable VPIO microphone input"
            )

            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_EnableIO,
                    kAudioUnitScope_Output,
                    0,
                    &enabled,
                    UInt32(MemoryLayout<UInt32>.size)
                ),
                "Enable VPIO speaker output"
            )

            var format = monoPCM16(sampleRate: sampleRate)
            let formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)

            // Client -> VPIO -> speaker.
            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioUnitProperty_StreamFormat,
                    kAudioUnitScope_Input,
                    0,
                    &format,
                    formatSize
                ),
                "Set VPIO playback client format"
            )

            // Microphone -> VPIO -> client.
            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioUnitProperty_StreamFormat,
                    kAudioUnitScope_Output,
                    1,
                    &format,
                    formatSize
                ),
                "Set VPIO capture client format"
            )

            var maximumFrames = maxFrames
            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioUnitProperty_MaximumFramesPerSlice,
                    kAudioUnitScope_Global,
                    0,
                    &maximumFrames,
                    UInt32(MemoryLayout<UInt32>.size)
                ),
                "Set VPIO maximum frames per slice"
            )

            let opaque = Unmanaged.passUnretained(self).toOpaque()

            var playbackStruct = AURenderCallbackStruct(
                inputProc: playbackCallback,
                inputProcRefCon: opaque
            )
            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioUnitProperty_SetRenderCallback,
                    kAudioUnitScope_Input,
                    0,
                    &playbackStruct,
                    UInt32(MemoryLayout<AURenderCallbackStruct>.size)
                ),
                "Install VPIO playback callback"
            )

            var captureStruct = AURenderCallbackStruct(
                inputProc: captureCallback,
                inputProcRefCon: opaque
            )
            try check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_SetInputCallback,
                    kAudioUnitScope_Global,
                    1,
                    &captureStruct,
                    UInt32(MemoryLayout<AURenderCallbackStruct>.size)
                ),
                "Install VPIO capture callback"
            )

            // Explicitly ensure voice processing is enabled (bypass = 0).
            var bypass: UInt32 = 0
            let bypassStatus = AudioUnitSetProperty(
                unit,
                kAUVoiceIOProperty_BypassVoiceProcessing,
                kAudioUnitScope_Global,
                0,
                &bypass,
                UInt32(MemoryLayout<UInt32>.size)
            )
            if bypassStatus != noErr {
                log("warning: unable to set VPIO bypass=0 (OSStatus \(bypassStatus)); continuing")
            }

            let captureBytes = Int(maxFrames) * MemoryLayout<Int16>.size
            captureMemory = UnsafeMutableRawPointer.allocate(
                byteCount: captureBytes,
                alignment: MemoryLayout<Int16>.alignment
            )

            log("direct VPIO client format=48000Hz/1ch/S16 on playback bus0 and capture bus1")

            try check(
                AudioUnitInitialize(unit),
                "AudioUnitInitialize(VoiceProcessingIO)"
            )

            warmupUntilNanos = DispatchTime.now().uptimeNanoseconds + 350_000_000

            try check(
                AudioOutputUnitStart(unit),
                "AudioOutputUnitStart(VoiceProcessingIO)"
            )

            let ready = """
            {"sample_rate":48000,"channels":1,"voice_processing":true,"backend":"direct_vpio"}
            """.data(using: .utf8) ?? Data()
            writeFrame(.ready, payload: ready)
            log("VoiceProcessingIO active: direct Audio Unit, 48 kHz mono full-duplex")
        } catch {
            AudioUnitUninitialize(unit)
            AudioComponentInstanceDispose(unit)
            audioUnit = nil
            throw error
        }
    }

    func renderPlayback(
        frames: UInt32,
        ioData: UnsafeMutablePointer<AudioBufferList>?
    ) -> OSStatus {
        guard let ioData else { return noErr }

        let buffers = UnsafeMutableAudioBufferListPointer(ioData)
        let frameCount = Int(frames)

        for index in 0..<buffers.count {
            guard let data = buffers[index].mData else { continue }
            let destination = data.assumingMemoryBound(to: Int16.self)

            if index == 0 {
                playback.fill(destination, count: frameCount)
            } else {
                for i in 0..<frameCount {
                    destination[i] = 0
                }
            }
            buffers[index].mDataByteSize = UInt32(frameCount * MemoryLayout<Int16>.size)
        }

        return noErr
    }

    func capture(
        flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
        timestamp: UnsafePointer<AudioTimeStamp>,
        frames: UInt32
    ) -> OSStatus {
        guard let unit = audioUnit, let captureMemory else {
            return noErr
        }
        guard frames <= maxFrames else {
            return kAudio_ParamError
        }

        let byteCount = Int(frames) * MemoryLayout<Int16>.size
        var buffer = AudioBuffer(
            mNumberChannels: channels,
            mDataByteSize: UInt32(byteCount),
            mData: captureMemory
        )
        var list = AudioBufferList(
            mNumberBuffers: 1,
            mBuffers: buffer
        )

        let status = AudioUnitRender(
            unit,
            flags,
            timestamp,
            1,
            frames,
            &list
        )
        guard status == noErr else {
            return status
        }

        if DispatchTime.now().uptimeNanoseconds < warmupUntilNanos {
            return noErr
        }

        let actualBytes = min(Int(list.mBuffers.mDataByteSize), byteCount)
        let payload = Data(bytes: captureMemory, count: actualBytes)
        writeFrame(.mic, payload: payload)
        return noErr
    }

    func schedulePlayback(_ data: Data) {
        playback.append(data)
    }

    func flush() {
        playback.clear()
    }

    func stop() {
        guard let unit = audioUnit else { return }

        AudioOutputUnitStop(unit)
        AudioUnitUninitialize(unit)
        AudioComponentInstanceDispose(unit)
        audioUnit = nil
        playback.clear()
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
        
        HINT: direct VoiceProcessingIO still returned kAudioUnitErr_FailedInitialization (-10875).
        This strongly suggests the current macOS default input/output hardware
        routes cannot form a compatible VoiceProcessingIO pair. Test with the
        built-in MacBook microphone AND built-in MacBook speakers selected in
        System Settings > Sound, then restart the helper.
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
