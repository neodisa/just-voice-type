# Auto system-audio capture (Core Audio process tap) — Design

**Date:** 2026-08-05
**Status:** Approved (brainstorm) → PoC-validated → architecture revised (see REVISION below)
**Feature line:** Call Mode. Supersedes the manual Aggregate Device requirement for
"hear the other side"; the manual path remains as a fallback.

---

## REVISION 2026-08-05 — pivot to a Swift helper (PoC-validated)

The PoC spike (Task 0) proved the tap itself works but **falsified two design
assumptions** below. This section supersedes the "In-process PyObjC" architecture and
the "reuse Recorder via sounddevice" read path. The product behaviour, tiers, config,
menu, and consent sections are unchanged.

**What the PoC found (macOS 26.5.1):**
- `AudioHardwareCreateProcessTap` + `AudioHardwareCreateAggregateDevice` succeed from
  Python/PyObjC (`err=0`); the audio-capture prompt did **not** deny. So the tap and
  permission path are feasible.
- **But the tap's audio does not surface as sounddevice/PortAudio input channels.** An
  aggregate built with the mic as master exposed only the mic's 1 channel; the tap
  channels were absent. The working reference (insidegui/AudioCap) reads the tap via a
  **Core Audio `AudioDeviceIOProc`**, not device enumeration.
- The PyObjC path is also fiddly for the required property getters (CFDictionary keys
  arrive as `bytes` → segfault unless decoded; `AudioObjectGetPropertyData` out-args are
  crash-prone).
- A small **Swift** PoC using AudioCap's exact recipe (global tap → aggregate with the
  **system output** as master + the tap w/ drift compensation + auto-start → `IOProc`)
  captured system audio cleanly: tap format **48000 Hz, 2 ch, float32**, measured
  `peak=0.1840` while audio played → **NON-SILENT ✅**.

**Revised architecture — Swift helper streaming PCM:**

- **`native/whisperflow_syscap.swift`** → compiled with `swiftc` to a bundled binary
  (ad-hoc signed with the app's identity, placed in `Contents/MacOS/`). It:
  - creates a global tap `CATapDescription(stereoGlobalTapButExcludeProcesses: [])`,
    `muteBehavior = .unmuted` (never mute what the user hears);
  - builds the aggregate exactly per AudioCap: `MainSubDevice` + `SubDeviceList` = the
    **default system output** UID, `TapList` = `[{DriftCompensation: true, UID: tap.uuid}]`,
    `IsPrivate: true`, `IsStacked: false`, `TapAutoStart: true`;
  - **also adds the default input mic as a sub-device (drift-compensated)** so both sides
    land in one stream (a `--no-mic` flag captures system only);
  - reads via `AudioDeviceCreateIOProcIDWithBlock` + `AudioDeviceStart`, wraps
    `inInputData` in an `AVAudioPCMBuffer`, **downmixes all input channels to mono**;
  - writes one JSON header line to stdout — `{"sample_rate":48000,"channels":1}` — then
    raw little-endian float32 mono frames; all logging goes to **stderr**;
  - on `SIGINT`/`SIGTERM`: `AudioDeviceStop` → destroy IOProc → destroy aggregate →
    destroy tap → exit. Never leak a global tap.
- **`system_audio.py`** (Python side, now a subprocess manager, not a CoreAudio bridge):
  - `is_supported()` — macOS ≥ 14.4 **and** the helper binary exists.
  - `choose_source(...)` — unchanged pure tiers (tap → manual → mic); `"tap"` now means
    "spawn the helper".
  - `SystemAudioCapture` — spawns the helper, reads the header + PCM on a background
    thread into a mono 48 kHz buffer, and exposes a `take_chunk(...)`/`stop()` surface
    matching what the control loop already calls on `Recorder`. Resample 48k→16k reuses
    the same linear-interp helper as `Recorder`.
  - This is **more** unit-testable than the sounddevice path: feed known header+bytes to
    the reader and assert the numpy chunks; the pure `choose_source` and a
    `parse_header`/`bytes→float32` decoder get real tests. Only the actual capture needs
    the guarded on-hardware test.
- **control_loop** wiring is as before but the `"tap"` branch starts a `SystemAudioCapture`
  instead of a `Recorder`; teardown sends `SIGTERM` and reaps. Feature-A recovery maps to
  "helper process died → respawn it" (same `RecoveryPolicy`, restart the subprocess).
- **Packaging:** build step compiles the Swift source and ad-hoc-signs it into the bundle;
  `NSAudioCaptureUsageDescription` stays required. **Residual check:** confirm the
  audio-capture TCC grant works when the helper runs under the app's `com.whisperflow.local`
  identity (the PoC ran under Terminal). Mitigating evidence: the bundle already holds
  Microphone TCC under that same ad-hoc identity.

**Still open / next validations:** (a) mic-inclusion in the helper actually captures both
sides on this machine (esp. with a Bluetooth default input); (b) in-app TCC under the
ad-hoc identity. Both are gated manual checks in the revised plan.

---

## Problem

Today Call Mode only captures the other side of a call if the user has manually set up
a virtual loopback driver (BlackHole / VB-Cable) plus an Aggregate Device and Multi-Output
Device in Audio MIDI Setup, then routed the call app's output there (see README "Call Mode").
If that setup is absent, **only the user's own microphone is recorded** — the whole point of a
call transcript (what everyone else said) is lost. The user's requirement: *"the program must
hear everything said inside — internal audio, automatically; on calls it's not just my voice
that matters."*

## Goal

When a call recording starts, **automatically** capture the **entire system audio output**
(all processes) mixed with the user's **microphone**, with **no** Audio MIDI Setup and **no**
loopback driver — on macOS 14.4+. Fall back to the existing manual Call Device path when the
tap is unavailable, unsupported, or fails/denied.

## Background / verified facts

- macOS 14.4+ exposes Core Audio **process taps**: `CATapDescription` +
  `AudioHardwareCreateProcessTap`, then wrap the tap UID in an aggregate device via
  `kAudioAggregateDeviceTapListKey` / `AudioHardwareCreateAggregateDevice`. The aggregate then
  appears as a **normal input device**, readable by PortAudio/`sounddevice` like any other.
  Reference sample (Swift): insidegui/AudioCap.
- Capturing system audio needs its own TCC category via the **`NSAudioCaptureUsageDescription`**
  Info.plist key (separate from microphone). First tap creation triggers the OS consent prompt.
- **Signing risk:** process taps key TCC off a **stable signing identity**. Our packaged app
  already runs under a stable ad-hoc identity `com.whisperflow.local` (Microphone + Accessibility
  TCC already attach there), but audio-capture is a *separate* category and sources warn that
  ad-hoc signing may be limited for it. **This is the primary unknown and must be de-risked by a
  PoC spike before committing to the full build.**
- Environment confirmed: macOS 26.5.1 (well above 14.4); `swiftc`/`xcrun` present (Swift-helper
  fallback is buildable); bundle `~/Applications/Voice Type.app/Contents/Info.plist` is editable
  and already carries `NSMicrophoneUsageDescription` / `NSAppleEventsUsageDescription`.
- No ready-made Python/ctypes example exists for these APIs (AudioCap is Swift). Target is a
  **PyObjC/ctypes in-process** bridge; Swift helper is the documented fallback if PyObjC proves
  unworkable.

## Architecture

Key isolation principle: all fiddly native CoreAudio lives behind a tiny interface, so the rest
of the app depends on a 3-method contract, not on CoreAudio internals.

### Unit 1 — `system_audio.py` (new module: CoreAudio bridge)

Native imports (PyObjC / CoreAudio) are done **lazily inside methods**, so the module imports
cleanly on any machine (tests, non-mac) and only touches CoreAudio when actually used.

- `is_supported() -> bool` — capability probe: macOS ≥ 14.4 **and** the required API symbols are
  importable. Returns `False` (never raises) otherwise.
- `class SystemAudioTap`:
  - `create(include_mic: bool = True) -> Optional[str]` — build a **global** process tap
    (`stereoGlobalTapButExcludeProcesses: []` = all processes on the default output), then a
    private/ephemeral **aggregate device** whose sub-device list is `[default input mic (if
    include_mic)] + [tap]`. Returns the aggregate device identifier (UID or name) that
    `sounddevice` can open, or `None` on any failure / TCC denial.
  - `destroy() -> None` — release the aggregate and the tap (`AudioHardwareDestroyAggregateDevice`
    / `AudioHardwareDestroyProcessTap`). **Idempotent.** Supports context-manager use
    (`__enter__`/`__exit__`).
- `choose_source(auto_enabled, tap_supported, tap_device, manual_device) -> (kind, device, reason)`
  — **pure** decision function (no CoreAudio), unit-testable. Three tiers, so an intended
    auto-capture call never silently dies — worst case it still records the user's own voice:
  - `auto_enabled and tap_supported and tap_device` → `("tap", tap_device, ...)`
  - else if `manual_device` set → `("manual", manual_device, ...)`
  - else → `("mic", None, ...)` — record from the default system microphone
    (`Recorder(device=None)`) and notify that only the user's voice is being captured.
  - `reason` carries a short machine-usable code (e.g. `tap_ok`, `tap_denied`, `tap_unsupported`,
    `manual_fallback`, `mic_only`) so the caller picks the right notification text.

### Unit 2 — `Recorder` (reused unchanged)

`Recorder(device=<aggregate id>, all_channels=True)` already downmixes the aggregate's channels
(mic + system) into one mono track (`_to_mono_native`). Feature-A recovery (`restart_stream`)
still applies: the `SystemAudioTap` is held alive for the whole call, so reopening the same
aggregate UID after a stall works. **Risk to verify in PoC/impl:** that `_reinit_portaudio()`
(PortAudio terminate/initialize) does not invalidate a programmatically-created aggregate; the
aggregate persists at the CoreAudio level, so reopening by identifier should still succeed.

### Unit 3 — control_loop / worker wiring

- `call_start`:
  1. If auto enabled and `system_audio.is_supported()`: `tap = SystemAudioTap(); dev = tap.create()`.
     On success, record from `dev` and stash `tap` in a holder for teardown.
  2. Else fall back to the configured manual Call Device (existing path).
  3. Else record from the default system microphone (`Recorder(device=None)`) and notify that
     only the user's voice is captured — an intended auto call never silently aborts.
  - `choose_source(...)` encodes tiers 1–3; the existing Recorder start/chunking flow then runs
    on the chosen device.
- `call_stop` / abort / transcribe-error / recovery `GIVE_UP` / app exit: after
  `recorder.stop()`, call `tap.destroy()` in a `finally`-style guard. **A global tap must never
  leak** — otherwise the OS "recording system audio" indicator stays on.

### Unit 4 — Permissions & bundle

- Add `NSAudioCaptureUsageDescription` to `Contents/Info.plist` with a user-facing reason string.
  The bundle is hand-assembled (not built from the repo), so the exact key/value and the update
  step are **documented** (README / this spec), applied manually when updating the installed app.
- First `create()` triggers the TCC prompt; the grant attaches to `com.whisperflow.local`.
  Denial → `create()` returns `None` → fallback + notify.

### Unit 5 — Menu / config

- New menu toggle **"Авто-захват системного звука"**, default **ON**, persisted in `config.py`
  (mirrors existing `call_device` persistence, with the same junk-tolerant load).
- When `is_supported()` is `False` (old macOS), the toggle is hidden/disabled and the manual path
  is used.

### Unit 6 — Consent / docs

- Capturing all system audio is sensitive; the TCC prompt is the OS gate. Update the existing
  Call Mode recording-consent note and the README to state plainly that during a call the app
  records **everything playing on the Mac**, and that this replaces the manual loopback setup on
  macOS 14.4+.

## Error handling

- Tap creation fails or is denied at `call_start` → `notify` ("Не удалось включить авто-захват
  системного звука — используется ручной Call Device / только микрофон") and proceed with the
  fallback rather than failing the call.
- Teardown is best-effort and idempotent; any exception in `destroy()` is swallowed and logged.

## Testing

- **Pure, unit-tested:** `choose_source(...)` truth table; `is_supported()` returns `False`
  cleanly when PyObjC/CoreAudio symbols are absent (so CI and non-mac dev envs don't break).
- **Not CI-testable:** real `create()`/`destroy()` CoreAudio behavior → covered by a manual PoC
  checklist and a **guarded** integration test that skips unless an env flag is set and
  macOS ≥ 14.4.
- Recorder/downmix and Feature-A recovery already covered by existing tests.
- Teardown-on-all-exits: primarily manual review of the `run_app` wiring (nested closures);
  extract the choose+teardown decision into a testable seam where feasible.

## Implementation order (de-risk first)

1. **PoC spike (throwaway).** Minimal script that creates tap+aggregate via PyObjC under the
   bundle identity, opens it, and confirms (a) the TCC prompt fires and (b) **non-silent** frames
   arrive. Answers the ad-hoc-TCC + PyObjC-feasibility unknowns.
   **Gate:** if this fails, stop and reassess — Swift helper, or Developer ID signing — before
   building anything else. Do not proceed on assumption.
2. `system_audio.py` — `is_supported`, `SystemAudioTap.create/destroy`, `choose_source` (+ pure
   tests).
3. Info.plist `NSAudioCaptureUsageDescription` + documented bundle-update step.
4. control_loop wiring (auto default, manual fallback) + guaranteed teardown on every exit path.
5. Menu toggle + config persistence.
6. README + consent note + memory update.

## Non-goals (YAGNI)

- No per-app tap (whole system output only).
- No automatic call-detection (that is the separate feature C).
- No older-macOS tap backport (fallback = existing manual Aggregate Device path).
- No raw audio saved (unchanged).

## Sources

- [Capturing system audio with Core Audio taps — Apple Developer](https://developer.apple.com/documentation/CoreAudio/capturing-system-audio-with-core-audio-taps)
- [AudioHardwareCreateProcessTap — Apple Developer](https://developer.apple.com/documentation/coreaudio/audiohardwarecreateprocesstap(_:_:))
- [NSAudioCaptureUsageDescription — Apple Developer](https://developer.apple.com/documentation/bundleresources/information-property-list/nsaudiocaptureusagedescription)
- [insidegui/AudioCap — sample code (macOS 14.4+)](https://github.com/insidegui/AudioCap)
- [AudioTee: capture system audio output on macOS — Strongly Typed](https://stronglytyped.uk/articles/audiotee-capture-system-audio-output-macos)
