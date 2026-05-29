#!/usr/bin/env python3
"""voice_type_cli.py — Just Voice Type, headless CLI (Apple Silicon)."""
from __future__ import annotations
import argparse, os, queue, subprocess, sys, tempfile, threading, time, wave
from dataclasses import dataclass
from typing import Optional

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2

def _require(pkg, pip_name=None):
    try:
        return __import__(pkg)
    except ImportError as e:
        name = pip_name or pkg
        print(f"\n[!] Package '{pkg}' not installed. pip install {name}\n", file=sys.stderr)
        raise SystemExit(1) from e

@dataclass
class Recorder:
    sample_rate: int = SAMPLE_RATE
    def __post_init__(self):
        self.sd = _require("sounddevice")
        self.np = _require("numpy")
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
    def _callback(self, indata, frames, t, status):
        if status: print(f"[audio] {status}", file=sys.stderr)
        with self._lock:
            if self._recording: self._frames.append(indata.copy())
    def start(self):
        with self._lock:
            if self._recording: return
            self._frames = []; self._recording = True
        self._stream = self.sd.InputStream(samplerate=self.sample_rate, channels=CHANNELS, dtype="int16", callback=self._callback)
        self._stream.start()
    def stop(self):
        with self._lock:
            if not self._recording: return None
            self._recording = False
        if self._stream is not None:
            self._stream.stop(); self._stream.close(); self._stream = None
        if not self._frames: return None
        audio = self.np.concatenate(self._frames, axis=0)
        if len(audio) / self.sample_rate < 0.3: return None
        path = os.path.join(tempfile.gettempdir(), f"voice_type_{int(time.time()*1000)}.wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(CHANNELS); wf.setsampwidth(SAMPLE_WIDTH); wf.setframerate(self.sample_rate)
            wf.writeframes(audio.tobytes())
        return path

class MLXTranscriber:
    def __init__(self, model, language):
        try: from mlx_whisper import transcribe
        except ImportError as e:
            print("\n[!] pip install mlx-whisper\n", file=sys.stderr); raise SystemExit(1) from e
        self._transcribe = transcribe; self.model = model; self.language = language
    def transcribe(self, wav_path):
        r = self._transcribe(wav_path, path_or_hf_repo=self.model, language=self.language, word_timestamps=False)
        return (r.get("text") or "").strip()

class FasterWhisperTranscriber:
    def __init__(self, model, language):
        try: from faster_whisper import WhisperModel
        except ImportError as e:
            print("\n[!] pip install faster-whisper\n", file=sys.stderr); raise SystemExit(1) from e
        self._model = WhisperModel(model, device="cpu", compute_type="int8"); self.language = language
    def transcribe(self, wav_path):
        segs, _ = self._model.transcribe(wav_path, language=self.language, vad_filter=True, beam_size=5)
        return " ".join(s.text.strip() for s in segs).strip()

def copy_to_clipboard(text):
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE); p.communicate(text.encode("utf-8"))

def read_clipboard():
    try: return subprocess.check_output(["pbpaste"]).decode("utf-8", errors="ignore")
    except Exception: return ""

def paste_via_cmd_v():
    subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'], check=False)

def deliver_text(text, do_paste, restore_clipboard):
    if not text: return
    prev = read_clipboard() if restore_clipboard else None
    copy_to_clipboard(text)
    if do_paste:
        time.sleep(0.05); paste_via_cmd_v()
    if restore_clipboard and prev is not None:
        def _r(): time.sleep(0.3); copy_to_clipboard(prev)
        threading.Thread(target=_r, daemon=True).start()

def parse_hotkey(name):
    kb = _require("pynput.keyboard", "pynput").keyboard
    name = name.lower().strip()
    a = {"right_option": kb.Key.alt_r, "ralt": kb.Key.alt_r, "right_alt": kb.Key.alt_r,
         "left_option": kb.Key.alt_l, "lalt": kb.Key.alt_l, "left_alt": kb.Key.alt_l,
         "fn": getattr(kb.Key, "fn", None), "right_shift": kb.Key.shift_r, "left_shift": kb.Key.shift_l,
         "right_ctrl": kb.Key.ctrl_r, "left_ctrl": kb.Key.ctrl_l,
         "right_cmd": kb.Key.cmd_r, "left_cmd": kb.Key.cmd_l}
    if name in a and a[name] is not None: return a[name]
    if name.startswith("f") and name[1:].isdigit():
        k = getattr(kb.Key, name, None)
        if k is not None: return k
    raise ValueError(f"Unknown hotkey: {name}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=("mlx","faster"), default="mlx")
    ap.add_argument("--model", default=None)
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--hotkey", default="right_option")
    ap.add_argument("--no-paste", action="store_true")
    ap.add_argument("--no-restore-clipboard", action="store_true")
    args = ap.parse_args()
    if args.model is None:
        args.model = "mlx-community/whisper-large-v3-mlx" if args.engine=="mlx" else "large-v3"
    print(f"[+] {args.engine} | {args.model} | {args.lang} | hotkey={args.hotkey}")
    print("[+] Loading model (first run downloads ~3GB)...")
    tr = MLXTranscriber(args.model, args.lang) if args.engine=="mlx" else FasterWhisperTranscriber(args.model, args.lang)
    rec = Recorder()
    jobs = queue.Queue()
    def worker():
        while True:
            wav = jobs.get()
            if wav is None: return
            try:
                t0 = time.time(); text = tr.transcribe(wav); dt = time.time()-t0
                if text:
                    print(f"[✓] ({dt:.1f}s) {text}")
                    deliver_text(text, do_paste=not args.no_paste, restore_clipboard=not args.no_restore_clipboard)
                else: print("[·] Empty.")
            except Exception as e: print(f"[!] {e}", file=sys.stderr)
            finally:
                try: os.remove(wav)
                except OSError: pass
    threading.Thread(target=worker, daemon=True).start()
    kb = _require("pynput.keyboard", "pynput").keyboard
    hk = parse_hotkey(args.hotkey)
    down = {"v": False}
    def on_press(key):
        if key == hk and not down["v"]:
            down["v"] = True; print("[●] Recording...", flush=True); rec.start()
    def on_release(key):
        if key == hk and down["v"]:
            down["v"] = False; print("[…] Transcribing...", flush=True)
            wav = rec.stop()
            if wav: jobs.put(wav)
            else: print("[·] Too short.")
    print("[+] Ready. Ctrl+C to quit.\n")
    with kb.Listener(on_press=on_press, on_release=on_release) as l:
        try: l.join()
        except KeyboardInterrupt: print("\n[+] Bye.")

if __name__ == "__main__":
    main()
