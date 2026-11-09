// WhisperFlowSysCap — capture the whole system audio output via a Core Audio
// process tap and stream it as mono float32 PCM to stdout.
//
// System audio ONLY. The user's own microphone is captured separately by the
// Python side and mixed in — adding a mic sub-device here breaks the aggregate
// on Bluetooth inputs (HFP) and delivers no frames, so it is deliberately omitted.
//
// Recipe follows insidegui/AudioCap: global tap -> aggregate device with the
// system output as the main/clock sub-device + the tap (drift-compensated) ->
// AudioDeviceIOProc read.
//
// Protocol: one JSON header line on stdout — {"sample_rate":48000,"channels":1}
// — then raw little-endian float32 mono frames. All logs go to stderr.
// SIGINT/SIGTERM tear down the IOProc, aggregate and tap, then exit cleanly.
//
// Build: swiftc -O -framework CoreAudio -framework AVFoundation -o WhisperFlowSysCap whisperflow_syscap.swift

import Foundation
import CoreAudio
import AVFoundation

func errlog(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

/// UID string of the current default device for the given selector (input/output).
func defaultDeviceUID(_ selector: AudioObjectPropertySelector) -> String? {
    var devID = AudioObjectID(0)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var addr = AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    if AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                  &addr, 0, nil, &size, &devID) != noErr || devID == 0 {
        return nil
    }
    var uid: Unmanaged<CFString>? = nil
    var usize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    var uaddr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceUID,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    if AudioObjectGetPropertyData(devID, &uaddr, 0, nil, &usize, &uid) != noErr { return nil }
    return uid?.takeRetainedValue() as String?
}

// ── 1. global process tap (all output, don't mute what the user hears) ───────
let tap = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tap.uuid = UUID()
tap.muteBehavior = .unmuted
var tapID = AudioObjectID(0)
guard AudioHardwareCreateProcessTap(tap, &tapID) == noErr, tapID != 0 else {
    errlog("AudioHardwareCreateProcessTap failed"); exit(1)
}
guard let outUID = defaultDeviceUID(kAudioHardwarePropertyDefaultOutputDevice) else {
    errlog("no default output device"); exit(1)
}

// ── 2. aggregate device holding the tap ──────────────────────────────────────
// PREFERRED: tap-only aggregate — no audio device inside it at all. Pulling a
// device in makes capture hostage to that device: with Bluetooth output (a
// headset in HFP mode during a call) the aggregate stops delivering IO
// entirely, which is exactly how the other party went missing from call
// transcripts. We read via IOProc, so the aggregate needs no public visibility
// and no device clock. Falls back to the documented "system output as master"
// layout if a tap-only aggregate can't be created or started on this machine.
func makeAggregate(withOutputDevice: Bool) -> AudioObjectID {
    var desc: [String: Any] = [
        kAudioAggregateDeviceNameKey as String: "WhisperFlow SysCap",
        kAudioAggregateDeviceUIDKey as String: "com.whisperflow.syscap.\(UUID().uuidString)",
        kAudioAggregateDeviceIsPrivateKey as String: true,
        kAudioAggregateDeviceIsStackedKey as String: false,
        kAudioAggregateDeviceTapAutoStartKey as String: true,
        kAudioAggregateDeviceTapListKey as String: [[
            kAudioSubTapDriftCompensationKey as String: true,
            kAudioSubTapUIDKey as String: tap.uuid.uuidString,
        ]],
    ]
    if withOutputDevice {
        desc[kAudioAggregateDeviceMainSubDeviceKey as String] = outUID
        desc[kAudioAggregateDeviceSubDeviceListKey as String] =
            [[kAudioSubDeviceUIDKey as String: outUID]]
    } else {
        desc[kAudioAggregateDeviceSubDeviceListKey as String] = [[String: Any]]()
    }
    var id = AudioObjectID(0)
    let err = AudioHardwareCreateAggregateDevice(desc as CFDictionary, &id)
    if err != noErr || id == 0 {
        errlog("aggregate (withOutputDevice=\(withOutputDevice)) failed: err=\(err)")
        return AudioObjectID(0)
    }
    return id
}

var usingOutputDevice = false
var aggID = makeAggregate(withOutputDevice: false)
if aggID == 0 {
    usingOutputDevice = true
    aggID = makeAggregate(withOutputDevice: true)
}
guard aggID != 0 else { errlog("could not create any aggregate device"); exit(1) }
errlog("aggregate ready (tapOnly=\(!usingOutputDevice))")

// ── 3. tap stream format (only for the advertised sample rate) ───────────────
var asbd = AudioStreamBasicDescription()
var asbdSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
var fmtAddr = AudioObjectPropertyAddress(
    mSelector: kAudioTapPropertyFormat,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
guard AudioObjectGetPropertyData(tapID, &fmtAddr, 0, nil, &asbdSize, &asbd) == noErr else {
    errlog("read tap format failed"); exit(1)
}
let sampleRate = Int(asbd.mSampleRate)

// ── 4. header + IOProc that downmixes to mono and writes to stdout ───────────
// Read the AudioBufferList DIRECTLY (float32) instead of assuming the tap's
// channel layout — the aggregate's input is mic-channels + tap-channels, which
// an AVAudioFormat built from the tap alone does not describe. Downmix every
// input channel (deinterleaved: one buffer per channel; interleaved: ch per
// buffer) to a single mono track. This is what makes the mic + system case work.
let out = FileHandle.standardOutput
out.write("{\"sample_rate\":\(sampleRate),\"channels\":1}\n".data(using: .utf8)!)

let queue = DispatchQueue(label: "com.whisperflow.syscap")
var procID: AudioDeviceIOProcID? = nil
let framesLock = NSLock()
var framesSeen = 0
let ioBlock: AudioDeviceIOBlock = { _, inInputData, _, _, _ in
    let abl = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inInputData))
    guard abl.count > 0 else { return }
    let ch0 = max(1, Int(abl[0].mNumberChannels))
    let frames = Int(abl[0].mDataByteSize) / (MemoryLayout<Float>.size * ch0)
    if frames == 0 { return }
    var mono = [Float](repeating: 0, count: frames)
    var contributing = 0
    for buf in abl {
        guard let mData = buf.mData else { continue }
        let ch = max(1, Int(buf.mNumberChannels))
        let n = min(frames, Int(buf.mDataByteSize) / (MemoryLayout<Float>.size * ch))
        let p = mData.assumingMemoryBound(to: Float.self)
        if ch == 1 {
            for i in 0..<n { mono[i] += p[i] }
        } else {
            let inv = 1.0 / Float(ch)
            for i in 0..<n {
                var s: Float = 0
                for c in 0..<ch { s += p[i * ch + c] }
                mono[i] += s * inv
            }
        }
        contributing += 1
    }
    if contributing > 1 {
        let inv = 1.0 / Float(contributing)
        for i in 0..<frames { mono[i] *= inv }
    }
    mono.withUnsafeBytes { out.write(Data($0)) }
    framesLock.lock()
    let first = framesSeen == 0
    framesSeen += frames
    framesLock.unlock()
    if first { errlog("first frames delivered") }
}
guard AudioDeviceCreateIOProcIDWithBlock(&procID, aggID, queue, ioBlock) == noErr,
      procID != nil else {
    errlog("AudioDeviceCreateIOProcIDWithBlock failed"); exit(1)
}

func cleanup() {
    if let p = procID {
        AudioDeviceStop(aggID, p)
        AudioDeviceDestroyIOProcID(aggID, p)
    }
    AudioHardwareDestroyAggregateDevice(aggID)
    AudioHardwareDestroyProcessTap(tapID)
}

signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
var signalSources: [DispatchSourceSignal] = []
for sig in [SIGINT, SIGTERM] {
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { cleanup(); exit(0) }
    src.resume()
    signalSources.append(src)
}

var startErr = AudioDeviceStart(aggID, procID!)
if startErr != noErr && !usingOutputDevice {
    // tap-only не стартовал на этой машине — пересобираем документированную
    // раскладку с системным выводом в качестве мастера
    errlog("tap-only start failed (err=\(startErr)); retrying with output device")
    if let p = procID { AudioDeviceDestroyIOProcID(aggID, p) }
    AudioHardwareDestroyAggregateDevice(aggID)
    usingOutputDevice = true
    aggID = makeAggregate(withOutputDevice: true)
    if aggID != 0 {
        var retryProc: AudioDeviceIOProcID? = nil
        if AudioDeviceCreateIOProcIDWithBlock(&retryProc, aggID, queue, ioBlock) == noErr,
           let rp = retryProc {
            procID = rp
            startErr = AudioDeviceStart(aggID, rp)
        }
    }
}
guard startErr == noErr, let procID = procID else {
    errlog("AudioDeviceStart failed (err=\(startErr))"); cleanup(); exit(1)
}
errlog("streaming system-audio mono f32 @ \(Int(asbd.mSampleRate))Hz (tapOnly=\(!usingOutputDevice))")
dispatchMain()
