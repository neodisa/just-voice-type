# Call Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer to record when another app turns on the microphone, stop a call recording once the call app leaves, and show the call for 3 s in hidden mode when the dictation key is pressed.

**Architecture:**
- `mic_users.py` reads Core Audio process objects through ctypes: which processes use input or output.
- `call_detect.Detector` is a pure state machine. It turns those snapshots into `Ask` / `Withdraw` / `Stop` events.
- `voice_type.py` polls every 2 s on a daemon thread and maps the events onto:
  - the notifier, which gains identifiers, withdraw and click actions;
  - the existing `call_stop` command.
- Two settings (`call_detect`, `call_auto_stop`) flow through config, settings_model, the protocol and the SwiftUI Calls section.

**Tech Stack:** Python 3.13, ctypes (CoreAudio/CoreFoundation), PyObjC (UserNotifications, AppKit), SwiftUI helper, unittest.

Spec: `docs/superpowers/specs/2026-11-11-call-detection-design.md`.
Tests: `/Users/sergeyarkhipov/whisper_flow/.venv/bin/python -m unittest discover -s tests -t .` from the worktree root.

---

## File map

| file | change |
|---|---|
| `mic_users.py` | new: `AudioClient`, `CoreAudioBackend`, `snapshot`, `is_supported`, `app_key`, `app_name`, `usage` |
| `call_detect.py` | new: `Detector`, events `Ask`/`Withdraw`/`Stop`, constants |
| `notifier.py` | `notify(ident=, user_info=)`, `withdraw`, `on_action`, click routing by `action` |
| `menubar_icon.py` | `Snapshot.peek`, `PEEK_SEC`, `frame()` respects peek |
| `system_audio.py` | `SystemAudioCapture.pid`, `CombinedCallCapture.helper_pid` |
| `config.py` | `call_detect`, `call_auto_stop`, `CALL_DETECT_MODES` |
| `i18n.py` | RU/EN strings |
| `settings_model.py` | View fields, `_calls` rows, `validate_set` |
| `native/settings/{Protocol,CallsSection}.swift`, `PROTOCOL.md`, `demo-state.json` | two rows |
| `voice_type.py` | state, apply handlers, snapshot peek, on_press peek, detection thread, offer click |
| `README.md` | Calls paragraph |
| tests | `test_mic_users.py`, `test_call_detect.py` new; `test_notifier.py`, `test_menubar_icon.py`, `test_config.py`, `test_settings_model.py`, `test_system_audio.py` extended |

---

### Task 1: `call_detect.Detector`

**Files:** Create `call_detect.py`, `tests/test_call_detect.py`.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

import call_detect as cd
from call_detect import Ask, Stop, Withdraw

ZOOM, CHROME, SIRI = "us.zoom.xos", "com.google.Chrome", "com.apple.siri"


class Base(unittest.TestCase):
    def setUp(self):
        self.d = cd.Detector()

    def poll(self, t, on_mic=(), playing=(), recording=False, busy=False, ask=True, auto_stop=True):
        return self.d.poll(t, set(on_mic), set(playing), recording=recording, busy=busy,
                           ask=ask, auto_stop=auto_stop)

    def hold(self, t0, t1, **kw):
        """Опрос каждые POLL_SEC на отрезке [t0, t1]; все события подряд."""
        out, t = [], t0
        while t <= t1:
            out += self.poll(t, **kw)
            t += cd.POLL_SEC
        return out


class TestOffer(Base):
    def test_offer_after_eight_seconds_once(self):
        self.assertEqual(self.hold(0, 6, on_mic=[ZOOM]), [])
        self.assertEqual(self.poll(8, on_mic=[ZOOM]), [Ask(ZOOM)])
        self.assertEqual(self.hold(10, 60, on_mic=[ZOOM]), [])

    def test_short_siri_gets_no_offer(self):
        self.assertEqual(self.hold(0, 4, on_mic=[SIRI]) + self.poll(6), [])

    def test_offer_is_withdrawn_and_comes_back_next_session(self):
        self.hold(0, 8, on_mic=[ZOOM])
        self.assertEqual(self.poll(10), [Withdraw(ZOOM)])
        self.assertEqual(self.hold(12, 18, on_mic=[ZOOM]), [])
        self.assertEqual(self.poll(20, on_mic=[ZOOM]), [Ask(ZOOM)])

    def test_no_offer_while_recording_busy_or_off(self):
        self.assertEqual(self.hold(0, 20, on_mic=[ZOOM], recording=True), [])
        d2 = Base("run"); d2.setUp()
        self.assertEqual(d2.hold(0, 20, on_mic=[ZOOM], busy=True), [])
        d3 = Base("run"); d3.setUp()
        self.assertEqual(d3.hold(0, 20, on_mic=[ZOOM], ask=False), [])

    def test_offer_after_busy_ends(self):
        self.hold(0, 10, on_mic=[ZOOM], busy=True)
        self.assertEqual(self.poll(12, on_mic=[ZOOM]), [Ask(ZOOM)])


class TestAutoStop(Base):
    def test_manual_start_links_the_app_on_the_mic(self):
        self.poll(0, on_mic=[ZOOM])
        self.poll(2, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.d.linked, {ZOOM})

    def test_stop_twenty_seconds_after_the_app_leaves(self):
        self.hold(0, 30, on_mic=[ZOOM], playing=[ZOOM], recording=True)
        self.assertEqual(self.hold(32, 50, recording=True), [])
        self.assertEqual(self.poll(52, recording=True), [Stop(ZOOM, 20.0)])
        self.assertEqual(self.hold(54, 70, recording=True), [])

    def test_muted_listener_keeps_recording(self):
        self.hold(0, 30, on_mic=[ZOOM], playing=[ZOOM], recording=True)
        self.assertEqual(self.hold(32, 300, playing=[ZOOM], recording=True), [])

    def test_in_person_meeting_never_stops(self):
        self.assertEqual(self.hold(0, 600, recording=True), [])

    def test_short_siri_during_in_person_meeting_is_not_linked(self):
        self.hold(0, 8, recording=True)
        self.hold(10, 14, on_mic=[SIRI], recording=True)
        self.assertEqual(self.d.linked, set())
        self.assertEqual(self.hold(16, 120, recording=True), [])

    def test_late_call_app_gets_linked(self):
        self.hold(0, 8, recording=True)
        self.hold(10, 20, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.d.linked, {ZOOM})

    def test_two_linked_apps_one_leaves(self):
        self.hold(0, 10, on_mic=[ZOOM, CHROME], recording=True)
        self.assertEqual(self.hold(12, 120, on_mic=[CHROME], recording=True), [])

    def test_auto_stop_off(self):
        self.hold(0, 10, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.hold(12, 120, recording=True, auto_stop=False), [])

    def test_returning_app_resets_the_quiet_clock(self):
        self.hold(0, 30, on_mic=[ZOOM], recording=True)
        self.hold(32, 40, recording=True)
        self.poll(42, playing=[ZOOM], recording=True)
        self.assertEqual(self.hold(44, 62, recording=True), [])
        self.assertEqual(self.poll(64, recording=True), [Stop(ZOOM, 20.0)])

    def test_manual_stop_resets_links_and_keeps_the_offer_memory(self):
        self.hold(0, 8, on_mic=[ZOOM])
        self.hold(10, 20, on_mic=[ZOOM], recording=True)
        self.assertEqual(self.hold(22, 60, on_mic=[ZOOM]), [])
        self.assertEqual(self.d.linked, set())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, expect failure** — `.venv/bin/python -m unittest tests.test_call_detect` → `ModuleNotFoundError: call_detect`.

- [ ] **Step 3: Implement `call_detect.py`**

```python
"""Звонок по микрофону: когда предложить запись и когда её остановить.

Чистая логика без Core Audio. Каждые POLL_SEC приложение передаёт, какие
программы (ключи mic_users.app_key) держат микрофон и какие играют звук,
и получает события:
- Ask(key): программа держит микрофон ASK_AFTER_SEC, звонок не пишется —
  предложить запись (раз за «сеанс микрофона» этой программы);
- Withdraw(key): программа отпустила микрофон — убрать предложение;
- Stop(key, quiet_for): все программы, связанные с записью, уже
  STOP_AFTER_SEC не держат микрофон и не играют звук — остановить запись.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

POLL_SEC = 2.0
# короче — Siri, системная диктовка, голосовые; звонок держит микрофон дольше
ASK_AFTER_SEC = 8.0
# пауза после звонка: короткий обрыв или переподключение не режет запись
STOP_AFTER_SEC = 20.0
MODES = ("ask", "off")


@dataclass(frozen=True)
class Ask:
    key: str


@dataclass(frozen=True)
class Withdraw:
    key: str


@dataclass(frozen=True)
class Stop:
    key: str
    quiet_for: float


class Detector:
    def __init__(self) -> None:
        self.mic_since: dict = {}
        self.asked: Set[str] = set()
        self.linked: Set[str] = set()
        self.quiet_since: Optional[float] = None
        self._recording = False

    def poll(
        self,
        now: float,
        on_mic: Iterable[str],
        playing: Iterable[str],
        *,
        recording: bool,
        busy: bool,
        ask: bool,
        auto_stop: bool,
    ) -> list:
        on_mic, playing = set(on_mic), set(playing)
        events: List[object] = []
        for key in list(self.mic_since):
            if key not in on_mic:
                del self.mic_since[key]
                if key in self.asked:
                    self.asked.discard(key)
                    events.append(Withdraw(key))
        for key in on_mic:
            self.mic_since.setdefault(key, now)

        if recording != self._recording:
            # начало записи связывает её со всеми, кто сейчас в микрофоне;
            # конец — отвязывает. asked живёт дольше записи: остановили
            # вручную посреди звонка — тот же звонок второй раз не предлагаем
            self.linked = set(on_mic) if recording else set()
            self.quiet_since = None
            self._recording = recording

        held = {k for k in on_mic if now - self.mic_since[k] >= ASK_AFTER_SEC}
        if recording:
            self.linked |= held
            events += self._stop_check(now, on_mic | playing, auto_stop)
        elif ask and not busy:
            for key in sorted(held - self.asked):
                self.asked.add(key)
                events.append(Ask(key))
        return events

    def _stop_check(self, now: float, active: Set[str], auto_stop: bool) -> list:
        if not self.linked:
            return []  # запись без программы звонка — только вручную
        if self.linked & active:
            self.quiet_since = None
            return []
        if self.quiet_since is None:
            self.quiet_since = now
        quiet = now - self.quiet_since
        if not auto_stop or quiet < STOP_AFTER_SEC:
            return []
        key = sorted(self.linked)[0]
        self.linked = set()  # один Stop на запись
        self.quiet_since = None
        return [Stop(key, quiet)]
```

- [ ] **Step 4: Run, expect pass.**
- [ ] **Step 5: Commit** — `git add call_detect.py tests/test_call_detect.py && git commit -m "feat: call detector — offer, withdraw and auto-stop events"`.

---

### Task 2: `mic_users`

**Files:** Create `mic_users.py`, `tests/test_mic_users.py`.

- [ ] **Step 1: Write the failing tests**

```python
import sys
import unittest

import mic_users as mu
from mic_users import AudioClient as C


class FakeBackend:
    supported = True

    def __init__(self, clients=(), input_running=True, fail=False):
        self._clients = list(clients)
        self._running = input_running
        self._fail = fail
        self.walks = 0

    def input_running(self):
        if self._fail:
            raise OSError("boom")
        return self._running

    def clients(self):
        self.walks += 1
        return list(self._clients)


ZOOM_IN = C(100, "us.zoom.xos", True, True)
ME = C(1, "com.whisperflow.local", True, False)
CHROME = C(200, "com.google.Chrome.helper", True, True)
MUSIC = C(300, "com.apple.Music", False, True)


class TestSnapshot(unittest.TestCase):
    def test_excludes_own_pids(self):
        b = FakeBackend([ZOOM_IN, ME])
        self.assertEqual(mu.snapshot({1}, backend=b), [ZOOM_IN])

    def test_idle_fast_path_skips_the_walk(self):
        b = FakeBackend([MUSIC], input_running=False)
        self.assertEqual(mu.snapshot(set(), backend=b), [])
        self.assertEqual(b.walks, 0)

    def test_need_output_walks_even_when_no_input_runs(self):
        b = FakeBackend([MUSIC], input_running=False)
        self.assertEqual(mu.snapshot(set(), need_output=True, backend=b), [MUSIC])

    def test_core_audio_failure_is_empty(self):
        logged = []
        b = FakeBackend(fail=True)
        self.assertEqual(mu.snapshot(set(), backend=b, log=logged.append), [])
        self.assertEqual(mu.snapshot(set(), backend=b, log=logged.append), [])
        self.assertEqual(len(logged), 1)

    def test_unsupported_backend_is_empty(self):
        b = FakeBackend([ZOOM_IN]); b.supported = False
        self.assertEqual(mu.snapshot(set(), backend=b), [])


class TestKeys(unittest.TestCase):
    def test_helper_suffixes_fold_into_the_app(self):
        self.assertEqual(mu.app_key(CHROME), "com.google.Chrome")
        self.assertEqual(mu.app_key(C(1, "com.microsoft.edgemac.helper.renderer", True, False)), "com.microsoft.edgemac")
        self.assertEqual(mu.app_key(C(1, "com.tinyspeck.slackmacgap.Helper", True, False)), "com.tinyspeck.slackmacgap")
        self.assertEqual(mu.app_key(ZOOM_IN), "us.zoom.xos")

    def test_no_bundle_falls_back_to_pid(self):
        self.assertEqual(mu.app_key(C(42, "", True, False)), "pid:42")

    def test_usage_splits_mic_and_output(self):
        u = mu.usage([ZOOM_IN, CHROME, MUSIC], name=lambda key, pid: key.upper())
        self.assertEqual(u.on_mic, frozenset({"us.zoom.xos", "com.google.Chrome"}))
        self.assertEqual(u.playing, frozenset({"us.zoom.xos", "com.google.Chrome", "com.apple.Music"}))
        self.assertEqual(u.names, {"us.zoom.xos": "US.ZOOM.XOS", "com.google.Chrome": "COM.GOOGLE.CHROME"})


class TestNames(unittest.TestCase):
    def test_running_app_by_bundle_wins(self):
        n = mu.app_name("com.google.Chrome", 200, by_bundle=lambda b: "Google Chrome", by_pid=lambda p: "Google Chrome Helper")
        self.assertEqual(n, "Google Chrome")

    def test_webkit_gpu_is_safari(self):
        self.assertEqual(mu.app_name("com.apple.WebKit.GPU", 5, by_bundle=lambda b: None, by_pid=lambda p: None), "Safari")

    def test_pid_then_key_then_generic(self):
        self.assertEqual(mu.app_name("x.y", 5, by_bundle=lambda b: None, by_pid=lambda p: "Y"), "Y")
        self.assertEqual(mu.app_name("x.y", 5, by_bundle=lambda b: None, by_pid=lambda p: None), "x.y")
        self.assertIsNone(mu.app_name("pid:5", 5, by_bundle=lambda b: "nope", by_pid=lambda p: None))


@unittest.skipUnless(sys.platform == "darwin", "Core Audio only on macOS")
class TestLive(unittest.TestCase):
    def test_snapshot_returns_a_list(self):
        self.assertIsInstance(mu.snapshot(set(), need_output=True), list)
```

- [ ] **Step 2: Run, expect `ModuleNotFoundError`.**

- [ ] **Step 3: Implement `mic_users.py`**

```python
"""Какие программы сейчас держат микрофон и играют звук (Core Audio, macOS 14.2+).

Те же данные, по которым macOS зажигает оранжевую точку: метаданные
процессов (pid, bundle id, идёт ли ввод/вывод), сам звук не читается.
ctypes без PyObjC — работает и в голом venv, и в бандле.
"""
from __future__ import annotations

import ctypes
import struct
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, List, Optional


@dataclass(frozen=True)
class AudioClient:
    pid: int
    bundle_id: str
    input: bool
    output: bool


@dataclass(frozen=True)
class Usage:
    on_mic: frozenset
    playing: frozenset
    names: dict  # ключ → имя для людей, только для тех, кто в микрофоне


def _fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode("ascii"))[0]


SYSTEM_OBJECT = 1
SCOPE_GLOBAL = _fourcc("glob")
SCOPE_INPUT = _fourcc("inpt")
PROCESS_LIST = _fourcc("prs#")
DEVICES = _fourcc("dev#")
STREAMS = _fourcc("stm#")
RUNNING_SOMEWHERE = _fourcc("gone")
PROC_PID = _fourcc("ppid")
PROC_BUNDLE = _fourcc("pbid")
PROC_INPUT = _fourcc("piri")
PROC_OUTPUT = _fourcc("piro")
_CF_UTF8 = 0x08000100


class _Addr(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


class CoreAudioBackend:
    """AudioObject* через ctypes. Любая ошибка — исключение; ловит snapshot()."""

    def __init__(self) -> None:
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        u32p = ctypes.POINTER(ctypes.c_uint32)
        addrp = ctypes.POINTER(_Addr)
        ca.AudioObjectHasProperty.argtypes = [ctypes.c_uint32, addrp]
        ca.AudioObjectHasProperty.restype = ctypes.c_ubyte
        ca.AudioObjectGetPropertyDataSize.argtypes = [ctypes.c_uint32, addrp, ctypes.c_uint32, ctypes.c_void_p, u32p]
        ca.AudioObjectGetPropertyData.argtypes = [ctypes.c_uint32, addrp, ctypes.c_uint32, ctypes.c_void_p, u32p, ctypes.c_void_p]
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_ubyte
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self._ca, self._cf = ca, cf
        self.supported = bool(ca.AudioObjectHasProperty(SYSTEM_OBJECT, ctypes.byref(_Addr(PROCESS_LIST, SCOPE_GLOBAL, 0))))

    def _size(self, obj: int, sel: int, scope: int) -> int:
        n = ctypes.c_uint32(0)
        st = self._ca.AudioObjectGetPropertyDataSize(obj, ctypes.byref(_Addr(sel, scope, 0)), 0, None, ctypes.byref(n))
        if st != 0:
            raise OSError(f"Core Audio size {sel:#x}: {st}")
        return n.value

    def _ids(self, obj: int, sel: int, scope: int = SCOPE_GLOBAL) -> List[int]:
        n = self._size(obj, sel, scope) // 4
        arr = (ctypes.c_uint32 * n)()
        size = ctypes.c_uint32(n * 4)
        st = self._ca.AudioObjectGetPropertyData(obj, ctypes.byref(_Addr(sel, scope, 0)), 0, None, ctypes.byref(size), arr)
        if st != 0:
            raise OSError(f"Core Audio list {sel:#x}: {st}")
        return list(arr)[: size.value // 4]

    def _scalar(self, obj: int, sel: int, ctype, scope: int = SCOPE_GLOBAL):
        v = ctype()
        size = ctypes.c_uint32(ctypes.sizeof(v))
        st = self._ca.AudioObjectGetPropertyData(obj, ctypes.byref(_Addr(sel, scope, 0)), 0, None, ctypes.byref(size), ctypes.byref(v))
        return v.value if st == 0 else None

    def _bundle(self, obj: int) -> str:
        ref = self._scalar(obj, PROC_BUNDLE, ctypes.c_void_p)
        if not ref:
            return ""
        try:
            buf = ctypes.create_string_buffer(512)
            ok = self._cf.CFStringGetCString(ref, buf, len(buf), _CF_UTF8)
            return buf.value.decode("utf-8") if ok else ""
        finally:
            self._cf.CFRelease(ref)

    def input_running(self) -> bool:
        """Хоть одно устройство ввода сейчас кем-то используется (дёшево)."""
        for dev in self._ids(SYSTEM_OBJECT, DEVICES):
            if self._size(dev, STREAMS, SCOPE_INPUT) == 0:
                continue
            if self._scalar(dev, RUNNING_SOMEWHERE, ctypes.c_uint32):
                return True
        return False

    def clients(self) -> List[AudioClient]:
        out = []
        for obj in self._ids(SYSTEM_OBJECT, PROCESS_LIST):
            inp = bool(self._scalar(obj, PROC_INPUT, ctypes.c_uint32))
            outp = bool(self._scalar(obj, PROC_OUTPUT, ctypes.c_uint32))
            if not (inp or outp):
                continue
            pid = self._scalar(obj, PROC_PID, ctypes.c_int32)
            if pid is None:
                continue
            out.append(AudioClient(int(pid), self._bundle(obj), inp, outp))
        return out


@lru_cache(maxsize=1)
def _default_backend():
    try:
        return CoreAudioBackend()
    except Exception:
        return None


def is_supported(backend=None) -> bool:
    b = backend or _default_backend()
    return bool(b is not None and b.supported)


_logged: set = set()


def snapshot(
    exclude_pids: Iterable[int],
    need_output: bool = False,
    backend=None,
    log: Callable[[str], object] = print,
) -> List[AudioClient]:
    """Процессы с идущим вводом или выводом, кроме exclude_pids.

    Без need_output и без единого работающего микрофона — сразу [] (дёшево).
    Ошибки Core Audio не пробрасываются: функция просто молчит."""
    b = backend or _default_backend()
    if b is None or not b.supported:
        return []
    try:
        if not need_output and not b.input_running():
            return []
        skip = set(exclude_pids)
        return [c for c in b.clients() if c.pid not in skip]
    except Exception as e:
        msg = f"[call-detect] Core Audio read failed: {type(e).__name__}: {e}"
        if msg not in _logged:
            _logged.add(msg)
            log(msg)
        return []


def app_key(c: AudioClient) -> str:
    """Один ключ на программу: хелперы браузеров и Electron — к основному bundle id."""
    if not c.bundle_id:
        return f"pid:{c.pid}"
    i = c.bundle_id.lower().find(".helper")
    return c.bundle_id[:i] if i > 0 else c.bundle_id


_KNOWN = {"com.apple.WebKit.GPU": "Safari"}


def _name_by_bundle(bundle_id: str) -> Optional[str]:
    from AppKit import NSRunningApplication

    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
    return str(apps[0].localizedName()) if apps and apps[0].localizedName() else None


def _name_by_pid(pid: int) -> Optional[str]:
    from AppKit import NSRunningApplication

    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    return str(app.localizedName()) if app is not None and app.localizedName() else None


def app_name(
    key: str,
    pid: int,
    by_bundle: Callable[[str], Optional[str]] = _name_by_bundle,
    by_pid: Callable[[int], Optional[str]] = _name_by_pid,
) -> Optional[str]:
    """Имя для людей; None — пусть вызывающий подставит «Другая программа»."""
    if key in _KNOWN:
        return _KNOWN[key]
    is_pid_key = key.startswith("pid:")
    for get in ((lambda: None) if is_pid_key else (lambda: by_bundle(key)), lambda: by_pid(pid)):
        try:
            name = get()
        except Exception:
            name = None
        if name:
            return name
    return None if is_pid_key else key


def usage(clients: Iterable[AudioClient], name: Callable[[str, int], Optional[str]] = app_name) -> Usage:
    on_mic, playing, names = set(), set(), {}
    for c in clients:
        key = app_key(c)
        if c.output:
            playing.add(key)
        if c.input:
            on_mic.add(key)
            if key not in names:
                n = name(key, c.pid)
                if n:
                    names[key] = n
    return Usage(frozenset(on_mic), frozenset(playing), names)
```

- [ ] **Step 4: Run, expect pass** (`tests.test_mic_users`).
- [ ] **Step 5: Live check** — open the mic from a second python and print `mic_users.snapshot({os.getpid()})`; expect one `org.python.python` client.
- [ ] **Step 6: Commit** — `feat: mic_users — which apps hold the microphone (Core Audio, ctypes)`.

---

### Task 3: notifier — identifiers, withdraw, click actions

**Files:** Modify `notifier.py`; extend `tests/test_notifier.py`.

- [ ] **Step 1: Failing tests** (append to `test_notifier.py`; `FakeCenter` gains `removed`):

```python
class FakeCenter:  # replace the existing one
    def __init__(self, error=None):
        self.requests = []
        self.removed = []
        self.error = error

    def addNotificationRequest_withCompletionHandler_(self, request, handler):
        self.requests.append(request)
        handler(self.error)

    def removeDeliveredNotificationsWithIdentifiers_(self, idents):
        self.removed.extend(idents)


class ActionTest(unittest.TestCase):
    def setUp(self):
        self.revealed, self.got = [], []
        self.handlers = {"record_call": self.got.append}

    def test_action_click_calls_its_handler(self):
        notifier.handle_click({"action": "record_call", "app": "us.zoom.xos"}, notifier.DEFAULT_ACTION,
                              self.revealed.append, self.handlers)
        self.assertEqual(self.got, [{"action": "record_call", "app": "us.zoom.xos"}])

    def test_unknown_action_and_dismiss_do_nothing(self):
        notifier.handle_click({"action": "nope"}, notifier.DEFAULT_ACTION, self.revealed.append, self.handlers)
        notifier.handle_click({"action": "record_call"}, "dismiss", self.revealed.append, self.handlers)
        self.assertEqual(self.got, [])

    def test_reveal_still_works_with_handlers(self):
        notifier.handle_click({"reveal": "/a.md"}, notifier.DEFAULT_ACTION, self.revealed.append, self.handlers)
        self.assertEqual((self.revealed, self.got), (["/a.md"], []))


class IdentTest(unittest.TestCase):
    def setUp(self):
        self.n = notifier.Notifier(log=lambda *a: None, fallback=lambda t, m: None)
        self.center = FakeCenter()
        self.n.use_center(self.center)

    def test_identifier_and_user_info(self):
        self.n.notify("Voice Type", "Zoom", ident="call-ask:us.zoom.xos",
                      user_info={"action": "record_call", "app": "us.zoom.xos"})
        r = self.center.requests[0]
        self.assertEqual(r.identifier(), "call-ask:us.zoom.xos")
        self.assertEqual(r.content().userInfo()["action"], "record_call")

    def test_withdraw(self):
        self.n.withdraw("call-ask:us.zoom.xos")
        self.assertEqual(self.center.removed, ["call-ask:us.zoom.xos"])

    def test_withdraw_without_center_is_a_no_op(self):
        notifier.Notifier(log=lambda *a: None).withdraw("x")
```

- [ ] **Step 2: Run, expect failures** (`handle_click()` takes 3 args; no `withdraw`).
- [ ] **Step 3: Implement**:
  - `ACTION_KEY = "action"`.
  - `handle_click(user_info, action, reveal, handlers=None)`: reveal path first; else look up `handlers[user_info["action"]]` and call it with `dict(user_info)`.
  - In the delegate: `handle_click(content.userInfo(), action, self.reveal, self.handlers)`.
  - In `Notifier`:
    - `__init__`: `self._handlers = {}`;
    - `on_action(name, fn)`: `self._handlers[name] = fn`;
    - `start()`: `self._delegate.handlers = self._handlers`;
    - `notify(title, message, reveal=None, ident=None, user_info=None)`: merges `reveal` into `user_info` and uses `ident or uuid4()`;
    - `withdraw(ident)`: calls `removeDeliveredNotificationsWithIdentifiers_([ident])` when a center exists, and swallows and logs errors.
- [ ] **Step 4: Run all notifier tests, expect pass.**
- [ ] **Step 5: Commit** — `feat: notifier — identifiers, withdraw and click actions`.

---

### Task 4: icon peek

**Files:** `menubar_icon.py`, `tests/test_menubar_icon.py`.

- [ ] **Step 1: Failing tests** (in the stealth test class):

```python
    def test_peek_shows_the_call_in_stealth(self):
        f = mi.frame(Snapshot(call_state="recording", call_elapsed=761, stealth=True, peek=True))
        self.assertEqual((f.symbol, f.tint, f.text), ("phone.fill", "rec", "12:41"))

    def test_peek_without_a_call_changes_nothing(self):
        self.assertEqual(mi.frame(Snapshot(stealth=True, peek=True)).symbol, "mic")
```
- [ ] **Step 2: Run, expect `TypeError: unexpected keyword 'peek'`.**
- [ ] **Step 3: Implement**:
  - `PEEK_SEC = 3.0`;
  - `Snapshot.peek: bool = False` with the comment «клавишу диктовки нажали во время скрытого звонка — на PEEK_SEC показать звонок»;
  - in `frame()`: `hide = s.stealth and not s.peek`.
- [ ] **Step 4: Run, expect pass.** **Step 5: Commit** — `feat: dictation key shows the hidden call for 3 s`.

---

### Task 5: config keys

**Files:** `config.py`, `tests/test_config.py`.

- [ ] **Step 1: Failing tests** (new class with the XDG setUp/tearDown copied from `TestConfig`):

```python
    def test_call_detect_defaults_and_roundtrip(self):
        cfg = config.load()
        self.assertEqual((cfg["call_detect"], cfg["call_auto_stop"]), ("ask", True))
        config.update(call_detect="off", call_auto_stop=False)
        cfg = config.load()
        self.assertEqual((cfg["call_detect"], cfg["call_auto_stop"]), ("off", False))

    def test_call_detect_junk_falls_back(self):
        config.save({"call_detect": "always", "call_auto_stop": "yes"})
        cfg = config.load()
        self.assertEqual((cfg["call_detect"], cfg["call_auto_stop"]), ("ask", True))

    def test_modes_match_the_detector(self):
        import call_detect
        self.assertEqual(config.CALL_DETECT_MODES, call_detect.MODES)
```
- [ ] **Step 2: Run, expect KeyError.**
- [ ] **Step 3: Implement**:
  - in `DEFAULTS`: `"call_detect": "ask"` and `"call_auto_stop": True`, with a comment;
  - `CALL_DETECT_MODES = ("ask", "off")`;
  - add both keys to `_defaults_copy`;
  - in `_validate`: `cfg["call_detect"] = v if v in CALL_DETECT_MODES else default`, and a bool check for `call_auto_stop`.
- [ ] **Step 4: Run, expect pass.** **Step 5: Commit** — `feat: config for call detection`.

---

### Task 6: settings model + strings

**Files:** `i18n.py`, `settings_model.py`, `tests/test_settings_model.py`.

- [ ] **Step 1: Failing tests** (TestCalls / TestValidateSet):

```python
    def test_detect_rows(self):
        c = self.calls(detect_supported=True)
        self.assertEqual(c["detect"]["value"], "ask")
        self.assertEqual([o["value"] for o in c["detect"]["options"]], ["ask", "off"])
        self.assertIsNone(c["detect"]["disabled_reason"])
        self.assertEqual(c["auto_stop"], {"value": True, "disabled_reason": None, "link": None})

    def test_detect_unsupported(self):
        c = self.calls(detect_supported=False)
        self.assertEqual(c["detect"]["value"], "off")
        self.assertEqual(c["detect"]["disabled_reason"], "Нужна macOS 14.2 или новее")
        self.assertFalse(c["auto_stop"]["value"])
        self.assertIsNotNone(c["auto_stop"]["disabled_reason"])

    # TestValidateSet
    def test_call_detect(self):
        self.assertEqual(self.ok("call_detect", "off", detect_supported=True), "off")
        self.ok("call_detect", "ask", detect_supported=True)
        self.bad("call_detect", "ask", detect_supported=False)
        self.ok("call_detect", "off", detect_supported=False)
        self.bad("call_detect", "always", detect_supported=True)
        self.assertIs(self.ok("call_auto_stop", False, detect_supported=True), False)
        self.bad("call_auto_stop", True, detect_supported=False)
        self.bad("call_auto_stop", "yes", detect_supported=True)
```
(Check `ok`/`bad` helpers accept view kwargs; they do for `auto_supported`.)

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**
  - `i18n.py`, RU:
    - `settings.calls.detect` «Когда другая программа включает микрофон»;
    - `.detect.caption` «Voice Type видит только, какие программы держат микрофон, — как оранжевая точка macOS. Звук не слушается.»;
    - `.detect.ask` «Спрашивать»;
    - `.detect.off` «Ничего не делать»;
    - `.detect.reason` «Нужна macOS 14.2 или новее»;
    - `.autostop` «Останавливать запись после звонка»;
    - `.autostop.caption` «Когда программа звонка отпустила микрофон и 20 секунд ничего не играет. Запись без программы звонка останавливается вручную.»;
    - `notify.call_offer` «{app} использует микрофон. Записать звонок?»;
    - `notify.call_offer.press` «{app} использует микрофон. Нажмите {key}, чтобы записать звонок.»;
    - `call.other_app` «Другая программа».
  - `i18n.py`, EN equivalents from the spec.
  - `settings_model.View`: `call_detect: str = "ask"`, `call_auto_stop: bool = True`, `detect_supported: bool = False`.
  - `_calls`: add the `detect` picker and the `auto_stop` toggle (value `off`/False and a reason when unsupported).
  - `validate_set`: `call_detect` (mode check, `ask` unavailable when unsupported); add `call_auto_stop` to the bool tuple, unavailable for True when unsupported.
- [ ] **Step 4: Run settings_model + i18n tests, expect pass.** The contract test will fail until Task 7.
- [ ] **Step 5: Commit** — `feat: settings rows for call detection`.

---

### Task 7: protocol + SwiftUI

**Files:**
- `native/settings/Protocol.swift`
- `native/settings/CallsSection.swift`
- `native/settings/PROTOCOL.md`
- `native/settings/demo-state.json`

- [ ] **Step 1:** `demo-state.json`, via a python one-off with `json.dump(..., ensure_ascii=False, indent=1)` and a trailing newline as before:
  - add `data.calls.detect` (picker shape: value `"ask"`, caption, `disabled_reason: null`, options ask/off);
  - add `data.calls.auto_stop` (`{"value": true, "disabled_reason": null, "link": null}`);
  - add the seven `calls.detect*` / `calls.autostop*` strings.
- [ ] **Step 2:** `Protocol.swift` `CallsData`: `let detect: PickerModel`, `let autoStop: ToggleModel`; CodingKeys `detect`, `autoStop = "auto_stop"`.
- [ ] **Step 3:** `CallsSection.swift`, after the stealth row:

```swift
                RowSep()
                PickerRow(label: store.s("calls.detect"), key: "call_detect", picker: c.detect)
                RowSep()
                ToggleRow(label: store.s("calls.autostop"), caption: store.s("calls.autostop.caption"),
                          key: "call_auto_stop", toggle: c.autoStop)
```
- [ ] **Step 4:** `PROTOCOL.md`: two lines under `calls`, and the set-key table gets `call_auto_stop` (bool) and `call_detect` (`"ask"|"off"`).
- [ ] **Step 5:** `./scripts/build_settings.sh`, then run the contract + helper tests (`tests.test_settings_contract tests.test_settings_helper`), expect pass.
- [ ] **Step 6:** Screenshot check: `native/JustVoiceTypeSettings --demo` (or the existing demo flag), open Calls, confirm both rows render.
- [ ] **Step 7: Commit** — `feat: Calls section — offer to record and auto-stop rows`.

---

### Task 8: system-audio helper pid

**Files:** `system_audio.py`, `tests/test_system_audio.py`.

- [ ] **Step 1: Failing test:** `SystemAudioCapture().pid is None` before start, and `CombinedCallCapture(system=fake).helper_pid` returns `fake.pid`.
- [ ] **Step 2: Implement:**
  - `SystemAudioCapture.pid` property: `self._proc.pid if self._proc is not None else None`;
  - `CombinedCallCapture.helper_pid` property: `getattr(self._system, "pid", None)`.
- [ ] **Step 3: Run, expect pass. Commit** — `feat: expose the system-audio helper pid`.

---

### Task 9: wire it into `voice_type.py`

**Files:** `voice_type.py`.

- [ ] **Step 1:** Imports `call_detect`, `mic_users`. After `call_stealth`, add:

```python
    call_detect_mode = {"value": cfg["call_detect"]}
    call_auto_stop = {"value": cfg["call_auto_stop"]}
    # клавишу диктовки нажали во время скрытого звонка → иконка на
    # menubar_icon.PEEK_SEC показывает звонок (см. on_press)
    call_peek = {"until": 0.0}
```
- [ ] **Step 2:** Add the apply handlers `apply_call_detect(mode)` and `apply_call_auto_stop(on)`, each saving through `config.update`. Register them in the apply dict under `"call_detect"` and `"call_auto_stop"`.
- [ ] **Step 3:** Pass `call_detect`, `call_auto_stop` and `detect_supported=mic_users.is_supported()` to the settings `View`, and `peek=now < call_peek["until"]` to `_snapshot`.
- [ ] **Step 4:** In `on_press`, the dictation-key branch while a call is active sets `call_peek["until"] = time.time() + menubar_icon.PEEK_SEC` before returning.
- [ ] **Step 5:** Before `threading.Thread(target=control_loop ...)`, add:
  - `mic_state`;
  - `own_pids()`: own pid plus `helper_pid` of the call recorder;
  - `offer_ident`, `offer_call(key)`, `record_from_offer(info)`, registered with `_notifier.on_action("record_call", ...)`;
  - `call_detect_loop()`, started on a daemon thread `call-detect` only when `mic_users.is_supported()`, otherwise a log line.

  The loop body:
  1. snapshot with `need_output=recording`;
  2. `usage`, then `det.poll(...)` with `busy = session active or paused`;
  3. `Ask` → `offer_call`;
  4. `Withdraw` → `_notifier.withdraw`;
  5. `Stop` → log `[call] auto-stop: {name} left the microphone {n}s ago` and `ctrl.put("call_stop")` if `call_session["active"]`.

  Errors are logged once per distinct message.
- [ ] **Step 6:** Full test suite, expect pass. `python -c "import ast; ast.parse(open('voice_type.py').read())"`.
- [ ] **Step 7: Commit** — `feat: call detection — offer to record, auto-stop, hidden-mode hint`.

---

### Task 10: README, spec touch-ups, finish

- [ ] **Step 1:** README Calls section: a short paragraph on the offer, auto-stop and privacy (EN, same voice as the rest).
- [ ] **Step 2:** Spec: the notifier has no `sound` parameter (notifications are already silent); the name lookup order is the known map, then running app by bundle, then pid, then key.
- [ ] **Step 3:** Full suite; commit `docs: call detection in the README`.
- [ ] **Step 4:** Ask the user to merge into main. After the merge, run `./scripts/build_settings.sh` in main and restart the installed app (see packaged-app-launch memory), then check the log for `call-detect` lines.
