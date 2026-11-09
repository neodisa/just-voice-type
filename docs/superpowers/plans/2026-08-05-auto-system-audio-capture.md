# Auto system-audio capture (Core Audio process tap) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a call recording starts, automatically capture the entire system audio output (all processes) mixed with the microphone — no loopback driver, no manual Audio MIDI Setup — on macOS 14.4+, falling back to the manual Call Device (or bare mic) when the tap is unavailable/denied.

**Architecture:** A new `system_audio.py` walls off all Core Audio process-tap code behind a 3-method contract (`is_supported`, `SystemAudioTap.create/destroy`, plus a pure `choose_source`). A tap on the default output is wrapped in a private aggregate device that also includes the mic; that aggregate is an ordinary input device, so the existing `Recorder`/`sounddevice` pipeline (and Feature-A recovery) records it unchanged. control_loop picks the source at `call_start` and guarantees tap teardown on every exit path.

**Tech Stack:** Python 3.13, PyObjC 12.1 (`CoreAudio` framework binding — already in the venv, all tap symbols present, no new dependency), `sounddevice`/PortAudio, `rumps` menubar, `unittest`.

**Design spec:** `docs/superpowers/specs/2026-08-05-auto-system-audio-capture-design.md`

> **⚠️ REVISED 2026-08-05 after the Task-0 PoC.** The PoC proved the tap works but that
> its audio must be read via a Core Audio `IOProc`, not sounddevice, and that the clean
> path is a small **Swift helper** (see the spec's REVISION section). **Follow the
> "REVISED TASK PLAN (Swift helper)" at the bottom of this file** — it supersedes Tasks
> 1–7 below, which described the abandoned in-process PyObjC/sounddevice approach. The
> `choose_source` pure logic and the config/menu/consent tasks carry over almost verbatim.

**Environment notes for the worker:**
- Run Python with the main-repo venv: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python` (worktrees have no own venv).
- Run the whole test suite: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -q`
- The installed app bundle is `~/Applications/Voice Type.app`; its launcher runs `~/whisper_flow/voice_type.py` under the stable ad-hoc identity `com.whisperflow.local`. TCC grants attach there. To see new code in the packaged app you must copy it to `~/whisper_flow/` and relaunch (`open`).

---

## Task 0: PoC spike — de-risk the tap (THROWAWAY, GATED, not TDD)

This is an exploration spike, not production code. It exists only to answer two unknowns before we build anything real. **Delete the script when done.**

**Files:**
- Create (throwaway): `scratch/poc_tap.py` (git-ignored / deleted after; do NOT commit)

- [ ] **Step 1: Write the PoC script**

```python
# scratch/poc_tap.py — THROWAWAY. Validates Core Audio process tap end-to-end.
import sys, time
import numpy as np
import CoreAudio, objc
import sounddevice as sd

def main():
    CATapDescription = objc.lookUpClass("CATapDescription")
    # Global tap: all processes on the default output, stereo mixdown.
    desc = CATapDescription.alloc().initStereoGlobalTapButExcludeProcesses_([])
    err, tap_id = CoreAudio.AudioHardwareCreateProcessTap(desc, None)
    print("create tap:", err, "id:", tap_id)
    if err != 0:
        print("FAIL create tap"); return 1

    tap_uid = str(desc.UUID().UUIDString())
    agg = {
        CoreAudio.kAudioAggregateDeviceNameKey: "WhisperFlow PoC Aggregate",
        CoreAudio.kAudioAggregateDeviceUIDKey: "com.whisperflow.poc.agg",
        CoreAudio.kAudioAggregateDeviceIsPrivateKey: 1,
        CoreAudio.kAudioAggregateDeviceIsStackedKey: 0,
        CoreAudio.kAudioAggregateDeviceTapListKey: [
            {CoreAudio.kAudioSubTapUIDKey: tap_uid}
        ],
        # NOTE: to also include the mic, add kAudioAggregateDeviceSubDeviceListKey
        # with the mic device UID. For the PoC, tap-only is enough to prove capture.
    }
    err, agg_id = CoreAudio.AudioHardwareCreateAggregateDevice(agg, None)
    print("create aggregate:", err, "id:", agg_id)
    if err != 0:
        print("FAIL create aggregate"); return 1

    # Find the aggregate in sounddevice by name and record 3s.
    name = "WhisperFlow PoC Aggregate"
    dev = next((i for i, d in enumerate(sd.query_devices())
                if d["name"] == name and d["max_input_channels"] > 0), None)
    print("sounddevice index:", dev)
    if dev is None:
        print("FAIL aggregate not visible to sounddevice"); return 1

    print(">>> PLAY SOME AUDIO NOW (e.g. a YouTube video) — recording 3s")
    rec = sd.rec(int(3 * 48000), samplerate=48000, channels=1, dtype="float32", device=dev)
    sd.wait()
    peak = float(np.max(np.abs(rec)))
    print(f"peak={peak:.4f}  {'NON-SILENT ✅' if peak > 0.01 else 'SILENT ❌'}")

    CoreAudio.AudioHardwareDestroyAggregateDevice(agg_id)
    CoreAudio.AudioHardwareDestroyProcessTap(tap_id)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add `NSAudioCaptureUsageDescription` to the bundle Info.plist** (the TCC prompt won't fire without it)

Run:
```bash
/usr/libexec/PlistBuddy -c 'Add :NSAudioCaptureUsageDescription string "Voice Type records the call'"'"'s system audio (all sides) so it can transcribe the whole conversation."' "$HOME/Applications/Voice Type.app/Contents/Info.plist"
```
(If the key already exists, use `Set` instead of `Add`.)

- [ ] **Step 3: Run the PoC under the app's code identity**

The definitive TCC test must run under `com.whisperflow.local`. Two ways, do the in-app one for the real answer:
- Quick first signal (may attribute TCC to Terminal): `"$HOME/Applications/Voice Type.app/Contents/MacOS/WhisperFlow-python" scratch/poc_tap.py`
- Definitive: temporarily add a menu item in the running packaged app that calls the PoC body, relaunch the app, click it, and watch `~/Library/Logs/WhisperFlow/whisper_flow.log`.

Expected: an OS prompt "Voice Type wants to record this computer's audio" appears; after granting, output shows `create tap: 0`, an aggregate index, and `NON-SILENT ✅` while audio plays.

- [ ] **Step 4: GATE — decide before building further**

- ✅ Prompt fires + `NON-SILENT` under `com.whisperflow.local` → proceed to Task 1 with the exact working call sequence discovered here.
- ❌ Prompt never fires / frames silent / `create tap` non-zero under ad-hoc → **STOP.** Report to the human. Options to reassess: Developer ID signing of the bundle, or the Swift-helper approach (spec Approach 2). Do not continue on assumption.

- [ ] **Step 5: Delete the throwaway**

```bash
rm -f scratch/poc_tap.py
```
Do not commit the PoC. Record the validated call sequence in the Task 1 notes / commit message instead.

---

## Task 1: `system_audio.py` — module skeleton, `is_supported`, `choose_source` (TDD)

**Files:**
- Create: `system_audio.py`
- Test: `tests/test_system_audio.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_system_audio.py
import unittest

import system_audio


class TestMacOSAtLeast(unittest.TestCase):
    def test_newer_is_supported(self):
        self.assertTrue(system_audio._macos_at_least(14, 4, ver="14.4"))
        self.assertTrue(system_audio._macos_at_least(14, 4, ver="26.5.1"))
        self.assertTrue(system_audio._macos_at_least(14, 4, ver="15.0"))

    def test_older_is_not(self):
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="14.3"))
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="13.6.1"))
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="10.15.7"))

    def test_garbage_version_is_false(self):
        self.assertFalse(system_audio._macos_at_least(14, 4, ver=""))
        self.assertFalse(system_audio._macos_at_least(14, 4, ver="not-a-version"))


class TestIsSupported(unittest.TestCase):
    def test_returns_bool_never_raises(self):
        self.assertIn(type(system_audio.is_supported()), (bool,))


class TestChooseSource(unittest.TestCase):
    def test_tap_wins_when_auto_and_supported_and_created(self):
        kind, dev, reason = system_audio.choose_source(
            auto_enabled=True, tap_supported=True,
            tap_device="agg-1", manual_device="My Aggregate",
        )
        self.assertEqual((kind, dev), ("tap", "agg-1"))
        self.assertEqual(reason, "tap_ok")

    def test_manual_when_auto_off(self):
        kind, dev, reason = system_audio.choose_source(
            auto_enabled=False, tap_supported=True,
            tap_device=None, manual_device="My Aggregate",
        )
        self.assertEqual((kind, dev), ("manual", "My Aggregate"))
        self.assertEqual(reason, "manual_fallback")

    def test_manual_when_tap_unsupported(self):
        kind, dev, reason = system_audio.choose_source(
            auto_enabled=True, tap_supported=False,
            tap_device=None, manual_device="My Aggregate",
        )
        self.assertEqual((kind, dev), ("manual", "My Aggregate"))
        self.assertEqual(reason, "tap_unsupported")

    def test_manual_when_tap_creation_failed(self):
        kind, dev, reason = system_audio.choose_source(
            auto_enabled=True, tap_supported=True,
            tap_device=None, manual_device="My Aggregate",
        )
        self.assertEqual((kind, dev), ("manual", "My Aggregate"))
        self.assertEqual(reason, "tap_denied")

    def test_mic_only_when_nothing_else(self):
        kind, dev, reason = system_audio.choose_source(
            auto_enabled=True, tap_supported=True,
            tap_device=None, manual_device=None,
        )
        self.assertEqual((kind, dev), ("mic", None))
        self.assertEqual(reason, "mic_only")

    def test_mic_only_when_auto_off_and_no_manual(self):
        kind, dev, reason = system_audio.choose_source(
            auto_enabled=False, tap_supported=False,
            tap_device=None, manual_device=None,
        )
        self.assertEqual((kind, dev), ("mic", None))
        self.assertEqual(reason, "mic_only")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_system_audio -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'system_audio'`

- [ ] **Step 3: Write the module skeleton + pure functions**

```python
# system_audio.py
"""Automatic system-audio capture via Core Audio process taps (macOS 14.4+).

All native Core Audio / PyObjC calls are imported LAZILY inside methods so this
module imports cleanly everywhere (tests, non-mac). The rest of the app depends
only on: is_supported(), SystemAudioTap.create()/destroy(), and the pure
choose_source() decision — never on Core Audio internals.
"""
from __future__ import annotations

import platform
import sys
from typing import Optional, Tuple

AGG_NAME = "WhisperFlow Auto Capture"
AGG_UID = "com.whisperflow.auto-capture.aggregate"


def _macos_at_least(major: int, minor: int, ver: "Optional[str]" = None) -> bool:
    if ver is None:
        try:
            ver = platform.mac_ver()[0]
        except Exception:
            return False
    try:
        parts = [int(x) for x in ver.split(".")[:2]]
    except (ValueError, AttributeError):
        return False
    while len(parts) < 2:
        parts.append(0)
    return (parts[0], parts[1]) >= (major, minor)


def is_supported() -> bool:
    """True only if the OS + PyObjC expose the process-tap API. Never raises."""
    if sys.platform != "darwin" or not _macos_at_least(14, 4):
        return False
    try:
        import CoreAudio  # noqa: PLC0415
        return all(
            hasattr(CoreAudio, n)
            for n in ("AudioHardwareCreateProcessTap", "AudioHardwareCreateAggregateDevice")
        )
    except Exception:
        return False


def choose_source(
    auto_enabled: bool,
    tap_supported: bool,
    tap_device: "Optional[str]",
    manual_device: "Optional[str]",
) -> "Tuple[str, Optional[str], str]":
    """Pick the call recording source. Returns (kind, device, reason_code).

    Three tiers so an intended auto call never silently dies:
      tap -> manual Call Device -> bare default mic.
    """
    if auto_enabled and tap_supported and tap_device:
        return ("tap", tap_device, "tap_ok")
    if manual_device:
        reason = (
            "manual_fallback" if not auto_enabled
            else ("tap_unsupported" if not tap_supported else "tap_denied")
        )
        return ("manual", manual_device, reason)
    return ("mic", None, "mic_only")
```

- [ ] **Step 4: Run to verify it passes**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_system_audio -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add system_audio.py tests/test_system_audio.py
git commit -m "feat(system-audio): module skeleton, is_supported, choose_source (pure, tested)"
```

---

## Task 2: `SystemAudioTap.create()/destroy()` — the native bridge

Port the exact working call sequence validated in Task 0. Native code cannot run in CI, so it is verified by a guarded integration test + manual check, and kept behind the clean interface.

**Files:**
- Modify: `system_audio.py` (add `SystemAudioTap`)
- Test: `tests/test_system_audio.py` (add guarded integration test)

- [ ] **Step 1: Add the guarded integration test**

```python
# append to tests/test_system_audio.py
import os


class TestSystemAudioTapIntegration(unittest.TestCase):
    """Real Core Audio — skipped unless explicitly enabled on capable hardware."""

    def setUp(self):
        if os.environ.get("WHISPERFLOW_TAP_TEST") != "1":
            self.skipTest("set WHISPERFLOW_TAP_TEST=1 to run real tap test")
        if not system_audio.is_supported():
            self.skipTest("process taps not supported on this OS/build")

    def test_create_returns_device_then_destroy_is_clean(self):
        tap = system_audio.SystemAudioTap()
        dev = tap.create(include_mic=True)
        try:
            self.assertIsInstance(dev, str)
            self.assertTrue(dev)
        finally:
            tap.destroy()
            tap.destroy()  # idempotent — must not raise
```

- [ ] **Step 2: Run to verify it skips cleanly**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_system_audio -q`
Expected: PASS with 1 skip (WHISPERFLOW_TAP_TEST not set)

- [ ] **Step 3: Implement `SystemAudioTap`** (adjust to the Task-0-validated sequence)

```python
# add to system_audio.py

def _log(msg: str) -> None:
    print(f"[system_audio] {msg}", file=sys.stderr)


class SystemAudioTap:
    """Holds a global process tap + a private aggregate device (mic + tap) alive
    for the duration of a call. create() returns the aggregate's name for
    sounddevice; destroy() releases both objects and is idempotent."""

    def __init__(self) -> None:
        self._tap_id = None
        self._agg_id = None

    def create(self, include_mic: bool = True) -> "Optional[str]":
        try:
            import CoreAudio
            import objc

            CATapDescription = objc.lookUpClass("CATapDescription")
            desc = CATapDescription.alloc().initStereoGlobalTapButExcludeProcesses_([])
            err, tap_id = CoreAudio.AudioHardwareCreateProcessTap(desc, None)
            if err != 0 or not tap_id:
                _log(f"create tap failed: err={err}")
                return None
            self._tap_id = tap_id
            tap_uid = str(desc.UUID().UUIDString())

            sub_devices = []
            if include_mic:
                mic_uid = _default_input_uid()
                if mic_uid:
                    sub_devices.append({CoreAudio.kAudioSubDeviceUIDKey: mic_uid})

            agg = {
                CoreAudio.kAudioAggregateDeviceNameKey: AGG_NAME,
                CoreAudio.kAudioAggregateDeviceUIDKey: AGG_UID,
                CoreAudio.kAudioAggregateDeviceIsPrivateKey: 1,
                CoreAudio.kAudioAggregateDeviceIsStackedKey: 0,
                CoreAudio.kAudioAggregateDeviceTapListKey: [
                    {CoreAudio.kAudioSubTapUIDKey: tap_uid}
                ],
                CoreAudio.kAudioAggregateDeviceSubDeviceListKey: sub_devices,
            }
            err, agg_id = CoreAudio.AudioHardwareCreateAggregateDevice(agg, None)
            if err != 0 or not agg_id:
                _log(f"create aggregate failed: err={err}")
                self.destroy()
                return None
            self._agg_id = agg_id
            return AGG_NAME
        except Exception as e:
            _log(f"create raised: {e}")
            self.destroy()
            return None

    def destroy(self) -> None:
        try:
            import CoreAudio
        except Exception:
            self._tap_id = None
            self._agg_id = None
            return
        if self._agg_id is not None:
            try:
                CoreAudio.AudioHardwareDestroyAggregateDevice(self._agg_id)
            except Exception as e:
                _log(f"destroy aggregate: {e}")
            self._agg_id = None
        if self._tap_id is not None:
            try:
                CoreAudio.AudioHardwareDestroyProcessTap(self._tap_id)
            except Exception as e:
                _log(f"destroy tap: {e}")
            self._tap_id = None

    def __enter__(self) -> "SystemAudioTap":
        return self

    def __exit__(self, *exc) -> None:
        self.destroy()


def _default_input_uid() -> "Optional[str]":
    """UID string of the current default input device, or None. Used to add the
    mic to the aggregate so the transcript has both sides."""
    try:
        import CoreAudio
        addr = CoreAudio.AudioObjectPropertyAddress(
            CoreAudio.kAudioHardwarePropertyDefaultInputDevice,
            CoreAudio.kAudioObjectPropertyScopeGlobal,
            CoreAudio.kAudioObjectPropertyElementMain,
        )
        err, dev_id = CoreAudio.AudioObjectGetPropertyData(
            CoreAudio.kAudioObjectSystemObject, addr, 0, None, None, None
        )
        if err != 0 or not dev_id:
            return None
        uid_addr = CoreAudio.AudioObjectPropertyAddress(
            CoreAudio.kAudioDevicePropertyDeviceUID,
            CoreAudio.kAudioObjectPropertyScopeGlobal,
            CoreAudio.kAudioObjectPropertyElementMain,
        )
        err, uid = CoreAudio.AudioObjectGetPropertyData(dev_id, uid_addr, 0, None, None, None)
        return str(uid) if err == 0 and uid else None
    except Exception:
        return None
```

> **Worker note:** the exact PyObjC out-argument calling convention for `AudioObjectGetPropertyData` and the aggregate dict keys are the parts most likely to need small adjustments — reconcile them with what the Task 0 spike actually ran and with insidegui/AudioCap. Keep the public method shapes (`create`/`destroy`/return type) exactly as above so later tasks stay valid.

- [ ] **Step 4: Verify (manual, on hardware)**

Run: `WHISPERFLOW_TAP_TEST=1 /Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_system_audio -q`
Expected: the integration test passes (device string returned, destroy idempotent). Then re-run without the env var to confirm the normal suite still skips it.

- [ ] **Step 5: Confirm pure tests still green + commit**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_system_audio -q`
Expected: PASS (skips integration)
```bash
git add system_audio.py tests/test_system_audio.py
git commit -m "feat(system-audio): SystemAudioTap create/destroy via Core Audio process tap"
```

---

## Task 3: config toggle `auto_system_audio` (TDD)

**Files:**
- Modify: `config.py:20-42` (DEFAULTS), `config.py:48-60` (`_defaults_copy`), `config.py:127-141` (`_validate`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_config.py (inside the existing test module)
class TestAutoSystemAudio(unittest.TestCase):
    def test_default_is_true(self):
        self.assertTrue(config.DEFAULTS["auto_system_audio"])
        self.assertTrue(config._defaults_copy()["auto_system_audio"])

    def test_roundtrip_false(self):
        cfg = config._validate({"auto_system_audio": False})
        self.assertFalse(cfg["auto_system_audio"])

    def test_non_bool_falls_back_to_default(self):
        cfg = config._validate({"auto_system_audio": "yes"})
        self.assertTrue(cfg["auto_system_audio"])
```
(If `tests/test_config.py` imports `config` and uses `unittest.TestCase` already — it does — just append this class.)

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config -q`
Expected: FAIL — `KeyError: 'auto_system_audio'`

- [ ] **Step 3: Implement**

In `config.py` `DEFAULTS` (after `"call_device": None,`):
```python
    # Авто-захват системного звука в Call Mode через Core Audio process tap
    # (macOS 14.4+). True = пытаться автоматически, иначе ручной Call Device.
    "auto_system_audio": True,
```
In `_defaults_copy()` return dict (after `"call_device": ...`):
```python
        "auto_system_audio": DEFAULTS["auto_system_audio"],
```
In `_validate()` (after the `call_device` block, before the hotkey-collision check):
```python
    asa = raw.get("auto_system_audio")
    if isinstance(asa, bool):
        cfg["auto_system_audio"] = asa
    else:
        cfg["auto_system_audio"] = DEFAULTS["auto_system_audio"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest tests.test_config -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): persist auto_system_audio toggle (default on)"
```

---

## Task 4: Wire source selection + teardown into control_loop

No unit test (nested closures in `run_app`); the decision logic is already tested via `choose_source`. Verify by reading + a manual smoke run.

**Files:**
- Modify: `voice_type.py` — imports; call-state holders near `call_recorder_holder` (~line 1823); the `call_start` branch (~line 1918); every call-end path (`call_stop`, GIVE_UP auto-stop, start-failure) to destroy the tap.

- [ ] **Step 1: Import the module**

In `voice_type.py` near `import call_health` / `import calls`:
```python
import system_audio
```

- [ ] **Step 2: Add a tap holder + read the toggle**

Near `call_recorder_holder = {"obj": None}`:
```python
    call_tap_holder = {"obj": None}  # SystemAudioTap kept alive during a call
```
Where the app loads config into locals (same place `current_call_device` is set up), add:
```python
    current_auto_sysaudio = {"value": cfg["auto_system_audio"]}
```

- [ ] **Step 3: Replace device selection in `call_start`**

Find, in the `elif cmd == "call_start":` branch, the current guard that reads `device = current_call_device["value"]` and rejects when unset. Replace the "pick device" logic with source selection (keep the surrounding try/except and Recorder start):

```python
                # выбрать источник: авто-tap → ручной Call Device → голый микрофон
                tap = None
                tap_dev = None
                if current_auto_sysaudio["value"] and system_audio.is_supported():
                    tap = system_audio.SystemAudioTap()
                    tap_dev = tap.create(include_mic=True)
                    if tap_dev is None:
                        tap.destroy()
                        tap = None
                kind, device, reason = system_audio.choose_source(
                    auto_enabled=current_auto_sysaudio["value"],
                    tap_supported=system_audio.is_supported(),
                    tap_device=tap_dev,
                    manual_device=current_call_device["value"],
                )
                if kind == "manual" and reason in ("tap_denied", "tap_unsupported"):
                    notify("Voice Type", "Авто-захват недоступен — пишу через выбранный Call Device")
                elif kind == "mic":
                    notify("Voice Type", "Авто-захват недоступен и Call Device не выбран — пишу только твой микрофон")
                try:
                    start_ts = time.time()
                    path = calls.start_transcript(start_ts)
                    # tap-устройство и Aggregate ищем по имени → all_channels даунмиксит
                    new_recorder = Recorder(device=device, all_channels=True)
                    new_recorder.start()
                    call_recorder_holder["obj"] = new_recorder
                    call_tap_holder["obj"] = tap
                    call_session["id"] += 1
                    call_session["active"] = True
                    call_session["start_ts"] = start_ts
                    call_session["path"] = path
                    call_health_holder["recovery"] = call_health.RecoveryPolicy()
                    call_health_holder["channels"] = call_health.ChannelHealthMonitor()
                    call_state["value"] = "recording"
                    ct.active = True
                    menu_dirty["value"] = True
                    play_sound(SOUND_START)
                except Exception as e:
                    log(f"[!] call recorder.start failed: {e}")
                    notify("Voice Type", f"Не удалось начать запись звонка: {e}")
                    play_sound(SOUND_ERROR)
                    if tap is not None:
                        tap.destroy()
                    call_tap_holder["obj"] = None
                    call_session["active"] = False
                    call_state["value"] = "idle"
                    ct.active = False
```

(The old "device not set → notify + abort" and "device not found" guards are removed: with the mic-only tier a call always has a source. If you want to keep a `_call_device_exists` sanity check, apply it only in the `kind == "manual"` branch.)

- [ ] **Step 4: Destroy the tap on the stop path**

In the `elif cmd == "call_stop":` branch, after `rest = call_recorder.stop() ...`, add:
```python
                _tap = call_tap_holder["obj"]
                if _tap is not None:
                    _tap.destroy()
                    call_tap_holder["obj"] = None
```

- [ ] **Step 5: Destroy the tap on the recovery GIVE_UP auto-stop**

The `GIVE_UP` branch already does `ctrl.put("call_stop")`, which reaches Step 4 — so no separate teardown is needed there. Add a one-line comment noting this so a future reader doesn't add a double-destroy.

- [ ] **Step 6: Byte-compile + full suite + manual smoke**

Run:
```bash
/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m py_compile voice_type.py
/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -q
```
Expected: compile OK; suite green.
Manual: copy to `~/whisper_flow/`, relaunch the app, start a call with audio playing, stop, confirm the transcript contains the other side and the "recording system audio" indicator turns OFF on stop (no leaked tap).

- [ ] **Step 7: Commit**

```bash
git add voice_type.py
git commit -m "feat(call): auto-pick system-audio tap as call source, with fallback + teardown"
```

---

## Task 5: Menu toggle "Авто-захват системного звука"

**Files:**
- Modify: `voice_type.py` — Call menu section (~line 1110 where `toggle_call` / `_call_device_menu` live); config save on toggle.

- [ ] **Step 1: Add the menu item + handler**

In the Call menu assembly (near `_call_device_menu()`), add a checkable item bound to `current_auto_sysaudio`:
```python
        def toggle_auto_sysaudio(self, sender):
            current_auto_sysaudio["value"] = not current_auto_sysaudio["value"]
            sender.state = 1 if current_auto_sysaudio["value"] else 0
            cfg = config.load()
            cfg["auto_system_audio"] = current_auto_sysaudio["value"]
            config.save(cfg)
            state_txt = "включён" if current_auto_sysaudio["value"] else "выключен"
            notify("Voice Type", f"Авто-захват системного звука {state_txt}")
```
Add the item in the menu list (disable/skip it if `not system_audio.is_supported()`):
```python
            if system_audio.is_supported():
                it = rumps.MenuItem("Авто-захват системного звука", callback=self.toggle_auto_sysaudio)
                it.state = 1 if current_auto_sysaudio["value"] else 0
                call_items.append(it)
```

- [ ] **Step 2: Byte-compile + suite**

Run:
```bash
/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m py_compile voice_type.py
/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t . -q
```
Expected: compile OK; green.
Manual: relaunch app, confirm the toggle appears (only on 14.4+), flips state, and persists across a restart.

- [ ] **Step 3: Commit**

```bash
git add voice_type.py
git commit -m "feat(menu): toggle for automatic system-audio capture"
```

---

## Task 6: Bundle Info.plist + documented update step

**Files:**
- Modify: `~/Applications/Voice Type.app/Contents/Info.plist` (runtime, manual — not in repo)
- Modify: `README.md` (document the key + the macOS-14.4 auto path)

- [ ] **Step 1: Ensure the usage-description key exists in the bundle**

Run (idempotent — use `Set` if it already exists from Task 0):
```bash
/usr/libexec/PlistBuddy -c 'Add :NSAudioCaptureUsageDescription string "Voice Type records the call'"'"'s system audio (all sides) so it can transcribe the whole conversation."' "$HOME/Applications/Voice Type.app/Contents/Info.plist" 2>/dev/null \
 || /usr/libexec/PlistBuddy -c 'Set :NSAudioCaptureUsageDescription "Voice Type records the call'"'"'s system audio (all sides) so it can transcribe the whole conversation."' "$HOME/Applications/Voice Type.app/Contents/Info.plist"
```

- [ ] **Step 2: Document it in README** (so a future bundle rebuild keeps the key)

Add to the Call Mode section: on macOS 14.4+ the app captures the other side automatically via a Core Audio process tap (grant the one-time "record this computer's audio" prompt); the manual loopback + Aggregate Device setup is now only a fallback for older macOS or if you turn the toggle off. Note the bundle's `Info.plist` must carry `NSAudioCaptureUsageDescription`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document automatic system-audio capture + NSAudioCaptureUsageDescription"
```

---

## Task 7: Consent note + memory update

**Files:**
- Modify: `README.md` (recording-consent note)

- [ ] **Step 1: Expand the consent note**

State plainly that with auto-capture on, a call recording captures **everything playing on the Mac** (not just the call app), and that recording others may require their consent depending on jurisdiction.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: consent note for whole-system audio capture"
```

- [ ] **Step 3: Update project memory** (assistant-side, not a repo commit)

Update the `call-mode` memory: limitation #2's "hear the other side needs manual loopback" is now automatic on macOS 14.4+ via `system_audio.py`; manual path is fallback. Note the TCC key and the ad-hoc-signing caveat resolved by the PoC.

---

## Self-Review notes (author)

- **Spec coverage:** tap+aggregate (Task 2), whole-output global tap (Task 2 `initStereoGlobalTapButExcludeProcesses_([])`), mic included (Task 2 `_default_input_uid`), auto-default + 3-tier fallback (`choose_source` Task 1 + wiring Task 4), teardown on all exits (Task 4 steps 3–5), Info.plist key (Tasks 0/6), toggle default-on + persist (Tasks 3/5), consent/docs (Tasks 6/7), PoC gate (Task 0). Recovery reuse — no task needed (Feature-A `restart_stream` already works on the aggregate; flagged as a risk to watch in Task 2/4 manual smoke).
- **Placeholder scan:** none — every code step carries concrete code; native-adjustment notes are explicit, not vague TODOs.
- **Type consistency:** `SystemAudioTap.create()->Optional[str]`, `destroy()`, `choose_source(...)->(kind,device,reason)` used identically in Tasks 1/2/4. Holder keys `call_tap_holder["obj"]`, local `current_auto_sysaudio["value"]` consistent across Tasks 4/5.

---
---

# REVISED TASK PLAN (Swift helper) — supersedes Tasks 1–7 above

Task 0 (PoC) is **DONE**: a Swift helper using AudioCap's recipe captured system audio
(48 kHz / 2 ch / f32, peak 0.184). The read path is a Core Audio `IOProc` inside a small
Swift binary that streams mono PCM to stdout; Python manages it as a subprocess.

Carried over verbatim from above: **Task 3 (config toggle)** and **Task 5 (menu toggle)** —
same code, just renumbered R5/R6c below. **`choose_source`** logic is unchanged.

### Task R1: extract `streaming.resample_to_16k` (TDD, DRY prep)

Both `Recorder` and the new capture need 48k→16k resampling. Extract it as a pure helper.

**Files:** Modify `streaming.py`, `voice_type.py` (`Recorder._resample_16k`); Test `tests/test_streaming.py`.

- [ ] Write failing test:
```python
class TestResampleTo16k(unittest.TestCase):
    def test_same_rate_is_passthrough(self):
        a = np.linspace(-1, 1, 100, dtype=np.float32)
        np.testing.assert_array_equal(streaming.resample_to_16k(a, 16000), a)
    def test_downsamples_length(self):
        a = np.zeros(48000, dtype=np.float32)
        out = streaming.resample_to_16k(a, 48000)
        self.assertEqual(len(out), 16000)
    def test_short_input_safe(self):
        self.assertEqual(len(streaming.resample_to_16k(np.zeros(1, dtype=np.float32), 48000)), 1)
```
- [ ] Run → FAIL (`AttributeError`).
- [ ] Implement in `streaming.py`:
```python
def resample_to_16k(audio: np.ndarray, src_sr: int) -> np.ndarray:
    """Linear-interp resample mono float32 to 16 kHz. src_sr==16000 → passthrough."""
    if src_sr == 16000 or len(audio) <= 1:
        return audio.astype(np.float32)
    new_len = int(round(len(audio) * 16000 / src_sr))
    if new_len <= 1:
        return audio.astype(np.float32)
    old_idx = np.linspace(0, len(audio) - 1, new_len)
    return np.interp(old_idx, np.arange(len(audio)), audio).astype(np.float32)
```
Then make `Recorder._resample_16k` delegate: `return streaming.resample_to_16k(audio_native, self._native_sr or SAMPLE_RATE)`.
- [ ] Run full suite → green. Commit: `refactor(streaming): extract resample_to_16k pure helper`.

### Task R2: `system_audio.py` pure parts (TDD)

**Files:** Create `system_audio.py`, `tests/test_system_audio.py`.

- [ ] Tests: `_macos_at_least` (as in old Task 1); `choose_source` truth table (as in old Task 1, unchanged); plus:
```python
class TestParseHeader(unittest.TestCase):
    def test_parses_sr_and_channels(self):
        self.assertEqual(system_audio.parse_header(b'{"sample_rate":48000,"channels":1}\n'),
                         (48000, 1))
    def test_bad_header_returns_none(self):
        self.assertIsNone(system_audio.parse_header(b'garbage\n'))

class TestDecodePCM(unittest.TestCase):
    def test_bytes_to_float32(self):
        import numpy as np
        a = np.array([0.0, 0.5, -0.5], dtype=np.float32)
        out = system_audio.decode_pcm(a.tobytes())
        np.testing.assert_array_equal(out, a)
    def test_partial_frame_ignored(self):
        # 5 bytes = 1 full float32 + 1 leftover byte -> 1 sample, no crash
        import numpy as np
        buf = np.float32(0.25).tobytes() + b"\x00"
        self.assertEqual(len(system_audio.decode_pcm(buf)), 1)
```
- [ ] Run → FAIL.
- [ ] Implement: `_macos_at_least`, `choose_source` (both exactly as old Task 1), plus:
```python
def is_supported(helper_path: "Optional[str]" = None) -> bool:
    if sys.platform != "darwin" or not _macos_at_least(14, 4):
        return False
    return _helper_exists(helper_path)

def parse_header(line: bytes) -> "Optional[Tuple[int, int]]":
    try:
        obj = json.loads(line.decode("utf-8").strip())
        return int(obj["sample_rate"]), int(obj["channels"])
    except Exception:
        return None

def decode_pcm(raw: bytes) -> "np.ndarray":
    import numpy as np
    n = len(raw) - (len(raw) % 4)          # whole float32s only
    return np.frombuffer(raw[:n], dtype="<f4").astype(np.float32)
```
(`_helper_exists`/`helper_path()` resolve the bundled binary next to `voice_type.py` or in `Contents/MacOS/`; return False when absent.)
- [ ] Run → PASS. Commit: `feat(system-audio): pure helpers (is_supported, choose_source, parse_header, decode_pcm)`.

### Task R3: Swift helper `native/whisperflow_syscap.swift` (+ build script)

Port the validated PoC, add the mic sub-device, stream to stdout, handle signals.
Native code is validated on hardware (manual), not CI.

**Files:** Create `native/whisperflow_syscap.swift`, `scripts/build_syscap.sh`.

- [ ] Write `native/whisperflow_syscap.swift`:
```swift
import Foundation
import CoreAudio
import AVFoundation

func errlog(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

func defaultDeviceUID(_ selector: AudioObjectPropertySelector) -> String? {
    var devID = AudioObjectID(0)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var addr = AudioObjectPropertyAddress(mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    if AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &devID) != noErr || devID == 0 { return nil }
    var uid: Unmanaged<CFString>? = nil
    var usize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    var uaddr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceUID,
        mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    if AudioObjectGetPropertyData(devID, &uaddr, 0, nil, &usize, &uid) != noErr { return nil }
    return uid?.takeRetainedValue() as String?
}

let withMic = !CommandLine.arguments.contains("--no-mic")

let tap = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tap.uuid = UUID(); tap.muteBehavior = .unmuted
var tapID = AudioObjectID(0)
guard AudioHardwareCreateProcessTap(tap, &tapID) == noErr, tapID != 0 else { errlog("tap create failed"); exit(1) }
guard let outUID = defaultDeviceUID(kAudioHardwarePropertyDefaultOutputDevice) else { errlog("no output uid"); exit(1) }

var subDevices: [[String: Any]] = [[kAudioSubDeviceUIDKey as String: outUID]]
if withMic, let micUID = defaultDeviceUID(kAudioHardwarePropertyDefaultInputDevice) {
    subDevices.append([kAudioSubDeviceUIDKey as String: micUID,
                       kAudioSubDeviceDriftCompensationKey as String: true])
    errlog("mic sub-device: \(micUID)")
}
let aggUID = "com.whisperflow.syscap.\(UUID().uuidString)"
let desc: [String: Any] = [
    kAudioAggregateDeviceNameKey as String: "WhisperFlow SysCap",
    kAudioAggregateDeviceUIDKey as String: aggUID,
    kAudioAggregateDeviceMainSubDeviceKey as String: outUID,
    kAudioAggregateDeviceIsPrivateKey as String: true,
    kAudioAggregateDeviceIsStackedKey as String: false,
    kAudioAggregateDeviceTapAutoStartKey as String: true,
    kAudioAggregateDeviceSubDeviceListKey as String: subDevices,
    kAudioAggregateDeviceTapListKey as String: [[
        kAudioSubTapDriftCompensationKey as String: true,
        kAudioSubTapUIDKey as String: tap.uuid.uuidString]],
]
var aggID = AudioObjectID(0)
guard AudioHardwareCreateAggregateDevice(desc as CFDictionary, &aggID) == noErr, aggID != 0 else { errlog("agg create failed"); exit(1) }

var asbd = AudioStreamBasicDescription()
var asbdSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
var fmtAddr = AudioObjectPropertyAddress(mSelector: kAudioTapPropertyFormat,
    mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
guard AudioObjectGetPropertyData(tapID, &fmtAddr, 0, nil, &asbdSize, &asbd) == noErr,
      let avFormat = AVAudioFormat(streamDescription: &asbd) else { errlog("tap format failed"); exit(1) }

let out = FileHandle.standardOutput
out.write("{\"sample_rate\":\(Int(asbd.mSampleRate)),\"channels\":1}\n".data(using: .utf8)!)

let queue = DispatchQueue(label: "com.whisperflow.syscap")
var procID: AudioDeviceIOProcID? = nil
let ioBlock: AudioDeviceIOBlock = { _, inInputData, _, _, _ in
    guard let buf = AVAudioPCMBuffer(pcmFormat: avFormat, bufferListNoCopy: inInputData, deallocator: nil) else { return }
    let frames = Int(buf.frameLength); if frames == 0 { return }
    guard let fch = buf.floatChannelData else { return }   // proven non-interleaved on 14.4+
    let ch = Int(buf.format.channelCount)
    var mono = [Float](repeating: 0, count: frames)
    for c in 0..<ch { let p = fch[c]; for i in 0..<frames { mono[i] += p[i] } }
    if ch > 1 { let inv = 1.0 / Float(ch); for i in 0..<frames { mono[i] *= inv } }
    mono.withUnsafeBytes { out.write(Data($0)) }
}
guard AudioDeviceCreateIOProcIDWithBlock(&procID, aggID, queue, ioBlock) == noErr, let procID = procID else { errlog("ioproc failed"); exit(1) }

func cleanup() {
    AudioDeviceStop(aggID, procID)
    AudioDeviceDestroyIOProcID(aggID, procID)
    AudioHardwareDestroyAggregateDevice(aggID)
    AudioHardwareDestroyProcessTap(tapID)
}
signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
var sources: [DispatchSourceSignal] = []
for sig in [SIGINT, SIGTERM] {
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { cleanup(); exit(0) }
    src.resume(); sources.append(src)
}
guard AudioDeviceStart(aggID, procID) == noErr else { errlog("device start failed"); cleanup(); exit(1) }
errlog("streaming mono f32 @ \(Int(asbd.mSampleRate))Hz (mic=\(withMic))")
dispatchMain()
```
- [ ] Write `scripts/build_syscap.sh`:
```bash
#!/bin/bash
set -euo pipefail
SRC="$(dirname "$0")/../native/whisperflow_syscap.swift"
OUT="${1:-$(dirname "$0")/../native/WhisperFlowSysCap}"
xcrun swiftc -O -framework CoreAudio -framework AVFoundation -o "$OUT" "$SRC"
codesign --force --sign - "$OUT"   # ad-hoc; bundle re-sign happens in Task R7
echo "built: $OUT"
```
- [ ] Build: `bash scripts/build_syscap.sh` → expect `built: …/WhisperFlowSysCap`.
- [ ] **Manual both-sides check (hardware):** run `./native/WhisperFlowSysCap | head -c 200 | xxd | head`, play audio AND speak — confirm the header line then non-zero bytes. (A fuller check happens once the Python reader exists in R4.)
- [ ] Commit: `feat(system-audio): Swift helper — global tap + mic aggregate, streams mono PCM`.

### Task R4: `SystemAudioCapture` subprocess reader (TDD)

**Files:** Modify `system_audio.py` (add class); Test `tests/test_system_audio.py` (fake helper).

- [ ] Add a test using a **fake helper** script (pure Python, emits a header + known frames) so no real audio is needed:
```python
class TestSystemAudioCaptureReader(unittest.TestCase):
    def _fake_helper(self, tmpdir):
        # writes header + 48000 float32 samples of 0.5, then sleeps until killed
        p = os.path.join(tmpdir, "fake_helper.py")
        with open(p, "w") as f:
            f.write(
                'import sys,struct,time\n'
                'sys.stdout.buffer.write(b\'{"sample_rate":48000,"channels":1}\\n\')\n'
                'sys.stdout.buffer.write(struct.pack("<48000f", *([0.5]*48000)))\n'
                'sys.stdout.buffer.flush()\n'
                'time.sleep(30)\n'
            )
        return p

    def test_reads_header_and_chunks(self):
        import tempfile, numpy as np
        with tempfile.TemporaryDirectory() as d:
            cap = system_audio.SystemAudioCapture(
                argv=[sys.executable, self._fake_helper(d)])
            cap.start()
            try:
                time.sleep(0.5)
                self.assertEqual(cap.sample_rate, 48000)
                chunk = cap.take_chunk(min_sec=0.5, target_sec=0.6, hard_max_sec=1.0)
                self.assertIsNotNone(chunk)
                # 48k mono @0.5 resampled to 16k, non-silent
                self.assertGreater(float(np.max(np.abs(chunk))), 0.4)
            finally:
                cap.stop()
```
- [ ] Run → FAIL.
- [ ] Implement `SystemAudioCapture` (spawn subprocess; background thread reads header then PCM into a 48k mono carry under a lock; `take_chunk` mirrors `Recorder.take_chunk` using `streaming.find_split_point` + `streaming.resample_to_16k`; `stop()` sends SIGTERM, joins, returns resampled tail; `seconds_since_last_frame()` for the recovery monitor). Default `argv = [helper_path()]`.
- [ ] Run → PASS (+ full suite green). Commit: `feat(system-audio): SystemAudioCapture subprocess reader`.

### Task R5: config toggle `auto_system_audio` — **same as original Task 3 above** (verbatim). Commit as there.

### Task R6: control_loop wiring + menu toggle

**Files:** Modify `voice_type.py`.

- [ ] Import `system_audio`; add `call_capture_holder = {"obj": None}` and `current_auto_sysaudio = {"value": cfg["auto_system_audio"]}`.
- [ ] In `call_start`, choose source:
```python
                kind, device, reason = system_audio.choose_source(
                    auto_enabled=current_auto_sysaudio["value"],
                    tap_supported=system_audio.is_supported(),
                    tap_device="tap" if system_audio.is_supported() else None,
                    manual_device=current_call_device["value"],
                )
                if kind == "tap":
                    cap = system_audio.SystemAudioCapture()
                    cap.start()
                    call_capture_holder["obj"] = cap
                    call_recorder_holder["obj"] = None
                else:
                    dev = device if kind == "manual" else None   # mic-only for "mic"
                    rec = Recorder(device=dev, all_channels=(kind == "manual"))
                    rec.start()
                    call_recorder_holder["obj"] = rec
                    call_capture_holder["obj"] = None
                    if reason in ("tap_denied", "tap_unsupported"):
                        notify("Voice Type", "Авто-захват недоступен — пишу через выбранный Call Device")
                    elif kind == "mic":
                        notify("Voice Type", "Авто-захват недоступен и Call Device не выбран — пишу только микрофон")
```
- [ ] In the call-active tick and `call_stop`, source = `call_capture_holder["obj"] or call_recorder_holder["obj"]`; both expose `take_chunk`/`stop`/`seconds_since_last_frame`. Feature-A recovery: for a `SystemAudioCapture`, "recover" = `stop()` + new `SystemAudioCapture().start()` (respawn) instead of `restart_stream()`.
- [ ] Teardown: on every call-end path, if `call_capture_holder["obj"]` set, `.stop()` it (SIGTERM) and clear the holder — never leak the helper/tap.
- [ ] Menu toggle: **same as original Task 5** (checkable "Авто-захват системного звука", persists to config, shown only when `system_audio.is_supported()`).
- [ ] `py_compile` + full suite + manual smoke (relaunch packaged app, start a call with audio playing + speaking, confirm transcript has both sides). Commit: `feat(call): use system-audio helper as auto call source + fallback + teardown`.

### Task R7: bundle integration, docs, consent, memory

**Files:** bundle `Contents/Info.plist` + `Contents/MacOS/WhisperFlowSysCap` (runtime, manual); `README.md`.

- [ ] Build the helper into the bundle and re-sign so the ad-hoc identity stays intact:
```bash
bash scripts/build_syscap.sh "$HOME/Applications/Voice Type.app/Contents/MacOS/WhisperFlowSysCap"
/usr/libexec/PlistBuddy -c 'Add :NSAudioCaptureUsageDescription string "Voice Type records the call'"'"'s system audio (all sides) so it can transcribe the whole conversation."' "$HOME/Applications/Voice Type.app/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep --sign - "$HOME/Applications/Voice Type.app"
```
  **Residual gate:** relaunch the app, start an auto call — confirm the "record this
  computer's audio" prompt is granted to *Voice Type* and capture works. If the ad-hoc
  re-sign resets Microphone/Accessibility grants, re-grant them. If audio-capture TCC
  cannot attach to the ad-hoc identity, escalate (Developer ID signing).
- [ ] `helper_path()` in `system_audio.py` resolves `Contents/MacOS/WhisperFlowSysCap` (and a dev fallback to `native/WhisperFlowSysCap`).
- [ ] README: document the macOS-14.4+ automatic path, the toggle, that the manual loopback is now a fallback, and the `NSAudioCaptureUsageDescription` key + build step. Consent note: an auto call records **everything playing on the Mac**.
- [ ] Commit: `docs: automatic system-audio capture (Swift helper) + consent`.
- [ ] Update the `call-mode` memory (assistant-side): auto system-audio via Swift helper; manual path is fallback; PoC-validated; residual ad-hoc-TCC checkpoint.

### Revised self-review
- **Coverage:** IOProc read (R3), whole-output global tap (R3), mic both-sides (R3 sub-device), 48k→16k reuse (R1), auto+fallback tiers (R2 `choose_source` + R6), subprocess read/teardown/recovery (R4, R6), config/menu (R5, R6), Info.plist+sign+consent+memory (R7), PoC gate (Task 0 done).
- **Placeholders:** none — Swift + reader + tests are concrete; `helper_path`/`SystemAudioCapture` bodies specified by behaviour with the exact interface they must match (`take_chunk`/`stop`/`seconds_since_last_frame`).
- **Type consistency:** `choose_source(...)->(kind,device,reason)`; source objects share `take_chunk(min_sec,target_sec,hard_max_sec)`/`stop()`/`seconds_since_last_frame()`; header is `{"sample_rate":int,"channels":int}`; PCM is little-endian float32 mono.
