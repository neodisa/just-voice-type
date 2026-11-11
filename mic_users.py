"""Какие программы сейчас держат микрофон и играют звук (Core Audio, macOS 14.2+).

Те же данные, по которым macOS зажигает оранжевую точку: метаданные
процессов (pid, bundle id, идёт ли ввод/вывод), сам звук не читается.
ctypes без PyObjC — работает и в голом venv, и в бандле.

Используется call_detect: звонок в Zoom, Meet, Telegram… виден как «другая
программа держит микрофон», без кода под каждое приложение.
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
    on_mic: frozenset  # ключи программ с идущим вводом
    playing: frozenset  # ключи программ с идущим выводом
    names: dict  # ключ → имя для людей (только для тех, кто в микрофоне)


def _fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode("ascii"))[0]


SYSTEM_OBJECT = 1  # kAudioObjectSystemObject
SCOPE_GLOBAL = _fourcc("glob")
SCOPE_INPUT = _fourcc("inpt")
PROCESS_LIST = _fourcc("prs#")  # kAudioHardwarePropertyProcessObjectList
DEVICES = _fourcc("dev#")  # kAudioHardwarePropertyDevices
STREAMS = _fourcc("stm#")  # kAudioDevicePropertyStreams
RUNNING_SOMEWHERE = _fourcc("gone")  # kAudioDevicePropertyDeviceIsRunningSomewhere
PROC_PID = _fourcc("ppid")
PROC_BUNDLE = _fourcc("pbid")
PROC_RUNNING = _fourcc("pir?")  # идёт ввод или вывод — один вызов вместо двух
PROC_INPUT = _fourcc("piri")
PROC_OUTPUT = _fourcc("piro")
_CF_UTF8 = 0x08000100


class _Addr(ctypes.Structure):
    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


class CoreAudioBackend:
    """AudioObject* через ctypes. Ошибки — исключения; их ловит snapshot()."""

    def __init__(self) -> None:
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        u32p = ctypes.POINTER(ctypes.c_uint32)
        addrp = ctypes.POINTER(_Addr)
        ca.AudioObjectHasProperty.argtypes = [ctypes.c_uint32, addrp]
        ca.AudioObjectHasProperty.restype = ctypes.c_ubyte
        ca.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, addrp, ctypes.c_uint32, ctypes.c_void_p, u32p,
        ]
        ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        ca.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, addrp, ctypes.c_uint32, ctypes.c_void_p, u32p, ctypes.c_void_p,
        ]
        ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetCString.restype = ctypes.c_ubyte
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self._ca, self._cf = ca, cf
        # объект процесса → (pid, bundle id): не меняются, пока процесс жив,
        # а строка bundle id — самый дорогой вызов обхода
        self._ident: dict = {}
        self.supported = bool(
            ca.AudioObjectHasProperty(SYSTEM_OBJECT, ctypes.byref(_Addr(PROCESS_LIST, SCOPE_GLOBAL, 0)))
        )

    def _size(self, obj: int, sel: int, scope: int) -> int:
        n = ctypes.c_uint32(0)
        st = self._ca.AudioObjectGetPropertyDataSize(
            obj, ctypes.byref(_Addr(sel, scope, 0)), 0, None, ctypes.byref(n)
        )
        if st != 0:
            raise OSError(f"Core Audio size of {sel:#x} on {obj}: {st}")
        return n.value

    def _ids(self, obj: int, sel: int, scope: int = SCOPE_GLOBAL) -> List[int]:
        count = self._size(obj, sel, scope) // 4
        arr = (ctypes.c_uint32 * max(count, 1))()
        size = ctypes.c_uint32(count * 4)
        st = self._ca.AudioObjectGetPropertyData(
            obj, ctypes.byref(_Addr(sel, scope, 0)), 0, None, ctypes.byref(size), arr
        )
        if st != 0:
            raise OSError(f"Core Audio list {sel:#x} on {obj}: {st}")
        return list(arr)[: size.value // 4]

    def _scalar(self, obj: int, sel: int, ctype, scope: int = SCOPE_GLOBAL):
        v = ctype()
        size = ctypes.c_uint32(ctypes.sizeof(v))
        st = self._ca.AudioObjectGetPropertyData(
            obj, ctypes.byref(_Addr(sel, scope, 0)), 0, None, ctypes.byref(size), ctypes.byref(v)
        )
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
            try:
                if self._size(dev, STREAMS, SCOPE_INPUT) == 0:
                    continue
            except OSError:
                continue  # устройство пропало между вызовами
            if self._scalar(dev, RUNNING_SOMEWHERE, ctypes.c_uint32):
                return True
        return False

    def clients(self) -> List[AudioClient]:
        out = []
        objs = self._ids(SYSTEM_OBJECT, PROCESS_LIST)
        for gone in set(self._ident) - set(objs):
            del self._ident[gone]
        for obj in objs:
            if not self._scalar(obj, PROC_RUNNING, ctypes.c_uint32):
                continue
            inp = bool(self._scalar(obj, PROC_INPUT, ctypes.c_uint32))
            outp = bool(self._scalar(obj, PROC_OUTPUT, ctypes.c_uint32))
            if not (inp or outp):
                continue
            ident = self._ident.get(obj)
            if ident is None:
                pid = self._scalar(obj, PROC_PID, ctypes.c_int32)
                if pid is None or pid <= 0:
                    continue
                ident = self._ident[obj] = (int(pid), self._bundle(obj))
            out.append(AudioClient(ident[0], ident[1], inp, outp))
        return out


@lru_cache(maxsize=1)
def _default_backend() -> Optional[CoreAudioBackend]:
    try:
        return CoreAudioBackend()
    except Exception:
        return None


def is_supported(backend=None) -> bool:
    """Список процессов Core Audio есть (macOS 14.2+)."""
    b = backend if backend is not None else _default_backend()
    return bool(b is not None and b.supported)


_logged: set = set()


def snapshot(
    exclude_pids: Iterable[int],
    need_output: bool = False,
    backend=None,
    log: Callable[[str], object] = print,
) -> List[AudioClient]:
    """Процессы с идущим вводом или выводом, кроме exclude_pids.

    Без need_output и без единого работающего микрофона — сразу [] (дёшево:
    полный обход процессов стоит ~20 мс). Ошибки Core Audio не
    пробрасываются: функция молчит, каждую разную ошибку пишет в лог раз."""
    b = backend if backend is not None else _default_backend()
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
    """Один ключ на программу: хелперы браузеров и Electron — к основному
    bundle id (com.google.Chrome.helper → com.google.Chrome)."""
    if not c.bundle_id:
        return f"pid:{c.pid}"
    i = c.bundle_id.lower().find(".helper")
    return c.bundle_id[:i] if i > 0 else c.bundle_id


# процессы без «своей» программы: звук WebKit идёт через общий GPU-процесс
_KNOWN = {"com.apple.WebKit.GPU": "Safari"}


def _name_by_bundle(bundle_id: str) -> Optional[str]:
    from AppKit import NSRunningApplication

    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
    name = apps[0].localizedName() if apps else None
    return str(name) if name else None


def _name_by_pid(pid: int) -> Optional[str]:
    from AppKit import NSRunningApplication

    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    name = app.localizedName() if app is not None else None
    return str(name) if name else None


def app_name(
    key: str,
    pid: int,
    by_bundle: Callable[[str], Optional[str]] = _name_by_bundle,
    by_pid: Callable[[int], Optional[str]] = _name_by_pid,
) -> Optional[str]:
    """Имя для людей. Сначала программа с этим bundle id (у хелпера Chrome по
    pid нашлось бы «Google Chrome Helper»), потом процесс по pid, потом сам
    ключ. None — пусть вызывающий подставит «Другая программа»."""
    if key in _KNOWN:
        return _KNOWN[key]
    by_pid_key = key.startswith("pid:")
    lookups = [] if by_pid_key else [lambda: by_bundle(key)]
    lookups.append(lambda: by_pid(pid))
    for lookup in lookups:
        try:
            name = lookup()
        except Exception:
            name = None
        if name:
            return name
    return None if by_pid_key else key


def usage(
    clients: Iterable[AudioClient],
    name: Callable[[str, int], Optional[str]] = app_name,
) -> Usage:
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
