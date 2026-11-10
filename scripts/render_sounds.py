#!/usr/bin/env python3
"""Рендер звуков cuelume в sounds/<стиль>/<событие>.wav.

cuelume синтезирует звуки на Web Audio, поэтому сам рендер идёт в браузере:
скрипт поднимает локальный сервер, страница scripts/render_sounds.html
рендерит каждую пару (стиль, событие) в OfflineAudioContext и присылает PCM
обратно. Здесь звук обрезается по хвосту и выравнивается по громкости под
старые системные звуки macOS (Tink/Pop/Ping/Basso на afplay -v 0.5), одним
общим усилением на все стили — относительные уровни cuelume не трогаем.

    .venv/bin/python scripts/render_sounds.py
    # открыть напечатанный адрес в браузере, дождаться «done»

Нужен один раз, при смене таблицы sounds.CUES или версии cuelume.
"""

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import soundfile as sf
from scipy.signal import lfilter, resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sounds  # noqa: E402

CUELUME_VERSION = "0.2.8"
CDN = f"https://cdn.jsdelivr.net/npm/cuelume@{CUELUME_VERSION}/dist"
SR = 48000
PEAK_CEILING = 0.97
TAIL_FLOOR_DB = -70.0
TAIL_KEEP_SEC = 0.02
FADE_SEC = 0.01

# ITU-R BS.1770 K-weighting at 48 kHz: high shelf, then highpass
_K_SHELF = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
_K_HIGHPASS = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
_WINDOW_SEC = 0.1


def loudness(x: np.ndarray) -> float:
    """Громкость короткого звука: самые громкие 100 мс, K-weighted, LUFS.
    x — (n,) или (n, каналы) при 48 кГц."""
    if x.ndim == 2:
        x = x.mean(axis=1)
    k = lfilter(*_K_HIGHPASS, lfilter(*_K_SHELF, x))
    w = int(_WINDOW_SEC * SR)
    sq = np.concatenate([[0.0], np.cumsum(k * k)])
    if len(k) <= w:
        best = sq[-1] / w
    else:
        best = float(np.max(sq[w:] - sq[:-w])) / w
    return -0.691 + 10 * np.log10(best + 1e-20)


def trim_tail(x: np.ndarray) -> np.ndarray:
    """Срезать тишину в конце, оставить 20 мс и сделать 10 мс затухание."""
    env = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    loud = np.nonzero(env > 10 ** (TAIL_FLOOR_DB / 20))[0]
    if len(loud) == 0:
        return x[:0]
    end = min(len(x), loud[-1] + 1 + int(TAIL_KEEP_SEC * SR))
    y = np.array(x[:end], dtype=np.float64)
    n = min(len(y), int(FADE_SEC * SR))
    fade = 0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))
    y[-n:] *= fade[:, None] if y.ndim == 2 else fade
    return y


def macos_reference() -> float:
    """Средняя громкость старых системных звуков, как их играл afplay -v 0.5."""
    levels = []
    for name in sorted(set(sounds._MACOS.values())):
        x, sr = sf.read(f"/System/Library/Sounds/{name}.aiff", always_2d=True)
        x = x.mean(axis=1)
        if sr != SR:
            g = np.gcd(SR, sr)
            x = resample_poly(x, SR // g, sr // g)
        levels.append(loudness(x * sounds.MACOS_VOLUME))
    return float(np.mean(levels))


def finish(raw: dict, out_dir: str) -> None:
    """raw: {(theme, event): (n, 2) float32} → WAV-файлы в out_dir."""
    trimmed = {k: trim_tail(v) for k, v in raw.items()}
    ref = macos_reference()
    default = [loudness(trimmed[("default", e)]) for e in sounds.EVENTS]
    gain_db = ref - float(np.mean(default))
    gain = 10 ** (gain_db / 20)
    peak = max(float(np.abs(v).max()) for v in trimmed.values())
    if peak * gain > PEAK_CEILING:
        gain = PEAK_CEILING / peak
    print(f"macOS reference {ref:.1f} LUFS, default theme {np.mean(default):.1f} LUFS, gain {20 * np.log10(gain):+.1f} dB")
    for (theme, event), x in sorted(trimmed.items()):
        y = x * gain
        os.makedirs(os.path.join(out_dir, theme), exist_ok=True)
        path = os.path.join(out_dir, theme, f"{event}.wav")
        sf.write(path, y, SR, subtype="PCM_16")
        print(f"  {theme:7} {event:16} {len(y) / SR:5.2f}s  {loudness(y):6.1f} LUFS  peak {np.abs(y).max():.2f}")


def plan(cuelume: str) -> dict:
    jobs = [
        {"theme": t, "event": e, "cue": sounds.CUES[e][0], "emphasis": sounds.CUES[e][1]}
        for t in sounds.CUELUME_THEMES
        for e in sounds.EVENTS
    ]
    return {"cuelume": cuelume, "sample_rate": SR, "jobs": jobs}


def serve(port: int, cuelume: str, cuelume_dir: str = "") -> dict:
    raw: dict = {}
    local = os.path.realpath(cuelume_dir) if cuelume_dir else ""
    done = threading.Event()
    page = open(os.path.join(HERE, "render_sounds.html"), "rb").read()
    body_plan = json.dumps(plan(cuelume)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, body=b"", ctype="text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._reply(200, page, "text/html; charset=utf-8")
            if path == "/plan.json":
                return self._reply(200, body_plan, "application/json")
            if local and path.startswith("/cuelume/"):
                f = os.path.realpath(os.path.join(local, path[len("/cuelume/"):]))
                if f.startswith(local + os.sep) and f.endswith(".js") and os.path.isfile(f):
                    return self._reply(200, open(f, "rb").read(), "text/javascript")
            return self._reply(404)

        def do_POST(self):
            url = urlparse(self.path)
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if url.path == "/save":
                q = parse_qs(url.query)
                theme, event = q.get("theme", [""])[0], q.get("event", [""])[0]
                if theme not in sounds.CUELUME_THEMES or event not in sounds.EVENTS:
                    return self._reply(400)
                raw[(theme, event)] = np.frombuffer(data, dtype="<f4").reshape(-1, 2)
                return self._reply(200)
            if url.path == "/done":
                self._reply(200)
                done.set()
                return
            return self._reply(404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"open http://127.0.0.1:{port}/ in a browser")
    done.wait()
    server.shutdown()
    return raw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--cuelume", default=CDN, help="base URL of cuelume's dist/ (default: jsDelivr)")
    ap.add_argument("--cuelume-dir", default="", help="serve cuelume's dist/ from this local folder instead")
    ap.add_argument("--out", default=sounds.SOUNDS_DIR)
    args = ap.parse_args()
    base = "/cuelume" if args.cuelume_dir else args.cuelume
    raw = serve(args.port, base, args.cuelume_dir)
    missing = [(t, e) for t in sounds.CUELUME_THEMES for e in sounds.EVENTS if (t, e) not in raw]
    if missing:
        sys.exit(f"missing renders: {missing}")
    finish(raw, args.out)


if __name__ == "__main__":
    main()
