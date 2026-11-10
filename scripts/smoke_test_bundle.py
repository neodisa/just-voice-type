#!/usr/bin/env python3
"""Smoke-test a built "Just Voice Type.app" without starting the menubar app.

    python3 scripts/smoke_test_bundle.py "dist/Just Voice Type.app"

Runs the bundle's own interpreter with the launcher's environment (and
nothing from the caller's), then checks that everything the app needs
imports and works from inside the bundle: the app modules, rumps / pynput /
sounddevice / Tk, TLS, numba, the Call Mode helper, a real Parakeet
transcription of a synthetic Russian phrase, and the Qwen polisher (mlx-lm +
transformers without torch). Finally it lists the files the process has
mapped and fails if any come from the system Python framework or a venv.

Models are taken from the HuggingFace cache (offline), so run it on a machine
that already has Parakeet and the polish model cached.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PHRASE = "Сегодня хорошая погода, давай откроем фигму и посмотрим макет."
EXPECT = ("погода", "макет")


def outer(app: Path) -> int:
    contents = app.resolve() / "Contents"
    site = contents / "Resources/site-packages"
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = Path(tmp) / "s.aiff", Path(tmp) / "s.wav"
        subprocess.run(["say", "-v", "Milena", "-o", aiff, PHRASE], check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav],
            check=True,
        )
        env = {
            "HOME": os.environ["HOME"],
            "PATH": "/usr/bin:/bin",
            "PYTHONHOME": str(contents / "Frameworks/Python.framework/Versions/3.13"),
            "PYTHONPATH": str(site),
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPYCACHEPREFIX": str(Path(tmp) / "pycache"),
            "SSL_CERT_FILE": str(site / "certifi/cacert.pem"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        return subprocess.run(
            [contents / "MacOS/JustVoiceType-python", "-u", Path(__file__).resolve(),
             "--inner", str(contents), str(wav)],
            env=env, cwd=contents / "Resources/app",
        ).returncode


def inner(contents: str, wav: str) -> int:
    failures: list[str] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn()
            print(f"  ok   {name}" + (f" — {detail}" if detail else ""))
        except Exception as e:  # noqa: BLE001 — report every failure
            failures.append(name)
            print(f"  FAIL {name} — {type(e).__name__}: {e}")

    sys.path.insert(0, os.getcwd())

    def interpreter():
        assert sys.executable.startswith(contents), sys.executable
        assert sys.prefix.startswith(contents), sys.prefix
        return f"{sys.version.split()[0]} at {sys.prefix[len(contents):]}"

    def no_torch():
        try:
            import torch  # noqa: F401
        except ImportError:
            return "not bundled"
        raise AssertionError("torch is importable")

    def app_modules():
        import importlib
        mods = ("voice_type", "live_typing", "terms", "system_audio", "calls",
                "polish", "config", "history", "mic_recovery", "gestures",
                "languages", "streaming", "call_health", "i18n", "menubar_icon",
                "settings_model", "settings_bridge", "login_item", "updates",
                "model_cache", "model_catalog", "sounds", "notifier")
        for m in mods:
            importlib.import_module(m)
        import voice_type
        return f"voice_type {voice_type.__version__}"

    def ui_libs():
        import pynput.keyboard  # noqa: F401
        import rumps  # noqa: F401
        import sounddevice as sd
        import tkinter
        return f"PortAudio {sd.get_portaudio_version()[1]}, Tcl {tkinter.Tcl().eval('info patchlevel')}"

    def tk_window():
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.update()
        root.destroy()

    def tls():
        import ssl
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        assert ctx.cert_store_stats()["x509_ca"] > 100
        return ssl.OPENSSL_VERSION

    def numba_jit():
        import numba
        assert numba.njit(lambda x: x + 1)(41) == 42

    def helper():
        import system_audio
        path = system_audio.helper_path()
        assert path.startswith(contents), path
        assert system_audio.is_supported(), "not supported on this macOS"
        return os.path.basename(path)

    def settings_window():
        import json
        import settings_bridge
        import settings_model
        path = settings_bridge.helper_path()
        assert path and path.startswith(contents), path
        fonts = os.path.join(contents, "Resources", "JustVoiceTypeSettings-Fonts")
        ttf = [f for f in os.listdir(fonts) if f.endswith(".ttf")]
        assert len(ttf) >= 3, ttf
        line = json.dumps(settings_model.build(settings_model.View(), rev=1)) + "\n"
        p = subprocess.run([path, "--protocol-selftest"], input=line.encode(),
                           capture_output=True, timeout=30)
        assert p.returncode == 0, p.stderr.decode()[-300:]
        return f"{os.path.basename(path)}, {len(ttf)} fonts"

    def sound_files():
        import sounds
        n = 0
        for theme in sounds.CUELUME_THEMES:
            for event in sounds.EVENTS:
                path, _ = sounds.resolve(event, theme)
                assert path.startswith(contents), path
                n += 1
        return f"{n} WAVs"

    def notifications():
        import UserNotifications  # noqa: F401
        import notifier
        return notifier.__name__

    def metal():
        import mlx.core as mx
        assert mx.metal.is_available()
        assert mx.__file__.startswith(contents), mx.__file__
        return f"mlx {mx.__version__}"

    def parakeet():
        import voice_type
        tr = voice_type.ParakeetTranscriber("mlx-community/parakeet-tdt-0.6b-v3", None)
        text = tr.transcribe(wav)
        assert all(w in text.lower() for w in EXPECT), text
        return repr(text)

    def polisher():
        import polish
        p = polish.Polisher()
        out = p._generate(polish.build_messages("ну вот это тест короче", "clean"),
                          max_tokens=24)
        assert out.strip(), "empty output"
        return f"{p.model_id.split('/')[-1]} → {out.strip()[:40]!r}"

    def mapped_files():
        lsof = subprocess.run(["/usr/sbin/lsof", "-p", str(os.getpid()), "-Fn"],
                              capture_output=True, text=True).stdout
        paths = [ln[1:] for ln in lsof.splitlines() if ln.startswith("n/")]
        leaks = [p for p in paths
                 if "/Library/Frameworks/Python.framework" in p or "/.venv/" in p]
        assert not leaks, leaks[:5]
        return f"{len(paths)} files, none outside the bundle"

    for name, fn in [
        ("interpreter is the bundled one", interpreter),
        ("torch is not bundled", no_torch),
        ("app modules import", app_modules),
        ("rumps / pynput / sounddevice / tkinter", ui_libs),
        ("Tk window", tk_window),
        ("TLS with certifi", tls),
        ("numba (llvmlite) JIT", numba_jit),
        ("Call Mode helper", helper),
        ("settings window helper + fonts", settings_window),
        ("sound files", sound_files),
        ("UserNotifications (PyObjC)", notifications),
        ("MLX Metal", metal),
        ("Parakeet transcription", parakeet),
        ("Qwen polisher (mlx-lm, no torch)", polisher),
        ("mapped libraries", mapped_files),
    ]:
        check(name, fn)

    print("PASS" if not failures else f"FAILED: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--inner":
        sys.exit(inner(sys.argv[2], sys.argv[3]))
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(outer(Path(sys.argv[1])))
