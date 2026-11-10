#!/usr/bin/env python3
"""Build a self-contained "Just Voice Type.app" and a drag-to-install DMG.

    python3 scripts/build_dmg.py [--ref v0.13.0] [--venv .venv] [--out dist]

Bundle layout:
  Contents/MacOS/JustVoiceType          launcher (bash): env + detached start
  Contents/MacOS/JustVoiceType-python   python.org interpreter, relinked to the
                                        bundled framework
  Contents/MacOS/WhisperFlowSysCap      Core Audio tap helper (Call Mode)
  Contents/MacOS/JustVoiceTypeSettings  SwiftUI settings window helper
  Contents/Resources/JustVoiceTypeSettings-Fonts
                                        its OFL fonts (outside MacOS/, which
                                        may hold only code for codesign)
  Contents/Frameworks/Python.framework  python.org 3.13 (stdlib, Tcl/Tk,
                                        OpenSSL), pruned and relinked
  Contents/Resources/site-packages      the venv's packages minus build-only
                                        ones (torch, pip, py2app …); mlx and
                                        mlx-metal swapped for macOS 14 wheels
  Contents/Resources/app                the app's sources at --ref, plus
                                        sounds/ (cuelume WAVs)

Models are not bundled (Parakeet alone is ~2.4 GB): they download into the
HuggingFace cache on first launch. The bundle is ad-hoc signed — without an
Apple Developer ID it cannot be notarized, so Gatekeeper asks once.

Needs: python.org Python 3.13 framework, the project venv, Xcode CLT
(swiftc, codesign, install_name_tool), network for the mlx wheels.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PY_VER = "3.13"
SRC_FW = Path(f"/Library/Frameworks/Python.framework/Versions/{PY_VER}")
APP_NAME = "Just Voice Type"
BUNDLE_ID = "com.justvoicetype.app"
EXE = "JustVoiceType"
PY_EXE = f"{EXE}-python"
MIN_MACOS = "14.0"
# Process taps exist from 14.2; system_audio.is_supported() only uses the
# helper on 14.4+, older systems fall back to the manual Call Device.
HELPER_MIN_MACOS = "14.4"
HF_DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
REPO = Path(__file__).resolve().parent.parent

# Distributions present in the dev venv but not needed at runtime. torch is
# pulled in only by mlx-whisper's checkpoint converter (torch_whisper.py);
# sympy/networkx/mpmath only by torch; the rest are build/packaging tools.
EXCLUDE_DISTS = {
    "torch", "sympy", "networkx", "mpmath",
    "pip", "setuptools", "wheel",
    "py2app", "macholib", "altgraph", "modulegraph",
}
# Distributions whose venv wheel targets the build machine's macOS (mlx ships
# per-OS builds); they are re-fetched for MIN_MACOS at the same version.
RETARGET_DISTS = ("mlx", "mlx-metal")

# Pruned from the copied framework: tests, IDLE, docs, headers, the
# framework's own site-packages (we use our own), the pythonw stub.
FW_PRUNE = {
    "lib/python3.13/test", "lib/python3.13/idlelib", "lib/python3.13/turtledemo",
    "lib/python3.13/ensurepip", "lib/python3.13/__phello__",
    "lib/python3.13/site-packages", "lib/pkgconfig",
    "bin", "include", "share", "Headers", "_CodeSignature",
    "Resources/English.lproj", "Resources/Python.app",
}

MACHO_MAGIC = {
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",  # thin 64/32
    b"\xca\xfe\xba\xbe",                        # fat
}


def run(*cmd, **kw) -> subprocess.CompletedProcess:
    kw.setdefault("check", True)
    return subprocess.run([str(c) for c in cmd], **kw)


def out(*cmd) -> str:
    return run(*cmd, capture_output=True, text=True).stdout


def log(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def is_macho(p: Path) -> bool:
    if p.is_symlink() or not p.is_file() or p.suffix == ".a":
        return False
    try:
        with open(p, "rb") as f:
            return f.read(4) in MACHO_MAGIC
    except OSError:
        return False


def machos(root: Path):
    for dp, _, files in os.walk(root):
        for name in files:
            p = Path(dp) / name
            if is_macho(p):
                yield p


def deps(p: Path) -> tuple[set[str], set[str]]:
    """(install ids, dependencies) across all architectures of a Mach-O."""
    ids = set(filter(None, out("otool", "-D", p).splitlines()[1:]))
    found: set[str] = set()
    for line in out("otool", "-L", p).splitlines():
        if line.startswith("\t"):
            found.add(line.strip().split(" (compatibility")[0])
    return {i.strip() for i in ids if not i.endswith(":")}, found - ids


# ── pieces ──────────────────────────────────────────────────────────────────


def app_version(ref: str) -> str:
    src = out("git", "-C", REPO, "show", f"{ref}:voice_type.py")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        sys.exit("cannot find __version__ in voice_type.py")
    return m.group(1)


def copy_framework(dst_fw: Path) -> Path:
    dst_ver = dst_fw / "Versions" / PY_VER

    def ignore(d: str, names: list[str]) -> set[str]:
        rel = os.path.relpath(d, SRC_FW)
        rel = "" if rel == "." else rel + "/"
        return {n for n in names if rel + n in FW_PRUNE or n == "__pycache__"}

    shutil.copytree(SRC_FW, dst_ver, symlinks=True, ignore=ignore)
    (dst_ver / "lib/python3.13/site-packages").mkdir()
    # Tcl/Tk: drop the build-against files (headers, stub libs, *Config.sh).
    # The shell scripts carried their signatures in xattrs, which a copy
    # loses, and codesign then refuses the whole framework.
    for fw in (dst_ver / "Frameworks").glob("*.framework"):
        versions = [v for v in (fw / "Versions").iterdir() if not v.is_symlink()]
        for p in list(fw.iterdir()) + [p for v in versions for p in v.iterdir()]:
            if p.name in ("Headers", "PrivateHeaders", "pkgconfig") or p.name.endswith(
                (".a", "Config.sh")
            ):
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    os.symlink(PY_VER, dst_fw / "Versions/Current")
    os.symlink("Versions/Current/Python", dst_fw / "Python")
    os.symlink("Versions/Current/Resources", dst_fw / "Resources")
    return dst_ver


def relink(files: list[Path], dst_ver: Path) -> list[Path]:
    """Rewrite absolute /Library/Frameworks/Python.framework references to
    @loader_path-relative ones inside the bundle. Returns changed files."""
    prefix = str(SRC_FW) + "/"
    changed = []
    for p in files:
        ids, ds = deps(p)
        args: list[str] = []
        for i in ids:
            if i.startswith(prefix):
                args += ["-id", "@rpath/" + i[len(prefix):]]
        for d in ds:
            if d.startswith(prefix):
                target = dst_ver / d[len(prefix):]
                rel = os.path.relpath(target, p.parent)
                args += ["-change", d, "@loader_path/" + rel]
        if args:
            run("install_name_tool", *args, p, stderr=subprocess.DEVNULL)
            changed.append(p)
    return changed


def dist_files(site: Path, dist: str) -> set[str]:
    """Top-level entries of site-packages that belong to `dist` (via RECORD)."""
    norm = re.sub(r"[-_.]+", "_", dist).lower()
    tops: set[str] = set()
    for info in site.glob("*.dist-info"):
        name = info.name[: -len(".dist-info")].rsplit("-", 1)[0]
        if re.sub(r"[-_.]+", "_", name).lower() != norm:
            continue
        tops.add(info.name)
        record = info / "RECORD"
        if record.exists():
            for line in record.read_text().splitlines():
                path = line.split(",", 1)[0]
                if path and not path.startswith(".."):
                    tops.add(path.split("/", 1)[0])
    return tops


def dist_version(site: Path, dist: str) -> str:
    norm = re.sub(r"[-_.]+", "_", dist).lower()
    for info in site.glob("*.dist-info"):
        name, ver = info.name[: -len(".dist-info")].rsplit("-", 1)
        if re.sub(r"[-_.]+", "_", name).lower() == norm:
            return ver
    sys.exit(f"{dist} is not installed in the venv")


def copy_site_packages(venv: Path, dst: Path) -> None:
    site = venv / f"lib/python{PY_VER}/site-packages"
    skip: set[str] = {"__pycache__", "distutils-precedence.pth"}
    for d in EXCLUDE_DISTS | set(RETARGET_DISTS):
        skip |= dist_files(site, d)
    shutil.copytree(
        site, dst, symlinks=True,
        ignore=lambda d, names: {n for n in names if n == "__pycache__"}
        | (skip & set(names) if Path(d) == site else set()),
    )
    pins = [f"{d}=={dist_version(site, d)}" for d in RETARGET_DISTS]
    plat = "macosx_" + MIN_MACOS.replace(".", "_") + "_arm64"
    log(f"fetching {', '.join(pins)} for {plat}")
    with tempfile.TemporaryDirectory() as tmp:
        run(
            venv / "bin/python", "-m", "pip", "install", "--quiet",
            "--disable-pip-version-check", "--no-deps", "--no-compile",
            "--only-binary=:all:", "--platform", plat,
            "--python-version", PY_VER, "--implementation", "cp",
            "--target", tmp, *pins,
        )
        for entry in Path(tmp).iterdir():
            if entry.name == "bin":
                continue
            target = dst / entry.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(entry), target)
    leftovers = [d for d in EXCLUDE_DISTS if dist_files(dst, d)]
    if leftovers:
        sys.exit(f"excluded dists still present: {leftovers}")


def copy_app_sources(ref: str, dst: Path) -> None:
    names = out("git", "-C", REPO, "ls-tree", "--name-only", ref).split()
    sources = [n for n in names if n.endswith(".py")] + ["LICENSE", "sounds"]
    dst.mkdir(parents=True)
    archive = subprocess.Popen(
        ["git", "-C", str(REPO), "archive", ref, *sources], stdout=subprocess.PIPE
    )
    run("tar", "-x", "-C", dst, stdin=archive.stdout)
    if archive.wait() != 0:
        sys.exit("git archive failed")


def build_helper(ref: str, dst: Path) -> None:
    src = out("git", "-C", REPO, "show", f"{ref}:native/whisperflow_syscap.swift")
    with tempfile.TemporaryDirectory() as tmp:
        swift = Path(tmp) / "whisperflow_syscap.swift"
        swift.write_text(src)
        run(
            "xcrun", "swiftc", "-O", "-target", f"arm64-apple-macos{HELPER_MIN_MACOS}",
            "-framework", "CoreAudio", "-framework", "AVFoundation",
            "-o", dst, swift,
        )


def build_settings_helper(ref: str, exe: Path, fonts: Path) -> None:
    """SwiftUI settings window (native/settings at --ref) and its fonts."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.Popen(
            ["git", "-C", str(REPO), "archive", ref, "native/settings"], stdout=subprocess.PIPE
        )
        run("tar", "-x", "-C", tmp, stdin=archive.stdout)
        if archive.wait() != 0:
            sys.exit("git archive native/settings failed")
        src = Path(tmp) / "native/settings"
        run(
            "xcrun", "swiftc", "-parse-as-library", "-O",
            "-target", f"arm64-apple-macos{MIN_MACOS}",
            "-o", exe, *sorted(src.glob("*.swift")),
        )
        fonts.mkdir(parents=True)
        for f in sorted((src / "Fonts").iterdir()):
            if f.suffix.lower() in (".ttf", ".txt"):
                shutil.copy2(f, fonts / f.name)


LAUNCHER = r"""#!/bin/bash
# Just Voice Type launcher: everything runs from inside this bundle — the
# python.org interpreter (Contents/MacOS), its framework (Contents/Frameworks),
# the packages and the app (Contents/Resources). Models live in the
# HuggingFace cache (~/.cache/huggingface), downloaded on first launch.
HERE="$(cd "$(dirname "$0")" && pwd)"
CONTENTS="$(dirname "$HERE")"
PY="$HERE/__PY_EXE__"
APP_DIR="$CONTENTS/Resources/app"
SITE="$CONTENTS/Resources/site-packages"
LOG_DIR="$HOME/Library/Logs/WhisperFlow"
HF_CACHE="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
MODEL_DIR="$HF_CACHE/models--__MODEL_DIR__"

mkdir -p "$LOG_DIR"

# One instance only — this bundle or a from-source/dev copy of the app; two
# would both react to the hotkey and type everything twice.
if /usr/bin/pgrep -f -- "-python -u .*voice_type\.py" >/dev/null 2>&1; then
    exit 0
fi

export PYTHONHOME="$CONTENTS/Frameworks/Python.framework/Versions/__PY_VER__"
export PYTHONPATH="$SITE"
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
# Keep the signed bundle untouched: bytecode goes to the user's cache.
export PYTHONPYCACHEPREFIX="$HOME/Library/Caches/JustVoiceType/pycache"
# python.org's OpenSSL has no system CA store; use certifi's.
export SSL_CERT_FILE="$SITE/certifi/cacert.pem"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ -d "$MODEL_DIR/snapshots" ]]; then
    # Model already cached: never touch the network (otherwise a start
    # without internet stalls on HuggingFace timeouts first).
    export HF_HUB_OFFLINE=1
    export TRANSFORMERS_OFFLINE=1
fi
# No osascript notification here: it would register the app with the legacy
# notification center, and macOS then refuses the app's own
# UNUserNotificationCenter. The app announces the model download itself.

cd "$APP_DIR"
# Detach, then exit: with `exec` LaunchServices treats us as a foreground app
# and the rumps menubar icon never appears.
nohup "$PY" -u "$APP_DIR/voice_type.py" "$@" \
    >>"$LOG_DIR/whisper_flow.log" \
    2>>"$LOG_DIR/whisper_flow.err.log" &
disown
exit 0
"""


def write_launcher(path: Path) -> None:
    text = (
        LAUNCHER.replace("__PY_EXE__", PY_EXE)
        .replace("__PY_VER__", PY_VER)
        .replace("__MODEL_DIR__", HF_DEFAULT_MODEL.replace("/", "--"))
    )
    path.write_text(text)
    path.chmod(0o755)


def write_info_plist(path: Path, version: str, icon: bool) -> None:
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleName": APP_NAME,
        "CFBundleExecutable": EXE,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSArchitecturePriority": ["arm64"],
        "LSRequiresNativeExecution": True,
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "Just Voice Type uses the microphone to transcribe your speech to text.",
        "NSAudioCaptureUsageDescription":
            "Call Mode records the other side of a call (system audio) to transcribe it.",
        "NSAppleEventsUsageDescription":
            "Just Voice Type sends keystrokes to insert the transcribed text.",
    }
    if icon:
        plist["CFBundleIconFile"] = "AppIcon"
    with open(path, "wb") as f:
        plistlib.dump(plist, f)


def sign(app: Path, dst_ver: Path, changed: list[Path]) -> None:
    def adhoc(p: Path, *extra: str) -> None:
        run("codesign", "--force", "--sign", "-", "--timestamp=none", *extra, p,
            stderr=subprocess.DEVNULL)

    # inside-out: relinked binaries, nested frameworks, Python.framework,
    # executables, then the bundle itself
    for p in changed:
        is_fw_main = p.parents[2].name == p.name + ".framework"
        if p.parent != app / "Contents/MacOS" and not is_fw_main:
            adhoc(p)
    for fw in ("Tcl", "Tk"):
        adhoc(dst_ver / "Frameworks" / f"{fw}.framework/Versions/8.6")
    adhoc(dst_ver)
    for name in (PY_EXE, "WhisperFlowSysCap", "JustVoiceTypeSettings"):
        adhoc(app / "Contents/MacOS" / name, "--identifier", BUNDLE_ID)
    adhoc(app, "--identifier", BUNDLE_ID)
    run("codesign", "--verify", "--deep", "--strict", app)


def make_dmg(app: Path, dmg: Path, version: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        run("ditto", app, stage / app.name)
        os.symlink("/Applications", stage / "Applications")
        if dmg.exists():
            dmg.unlink()
        run(
            "hdiutil", "create", "-quiet", "-volname", f"{APP_NAME} {version}",
            "-srcfolder", stage, "-fs", "HFS+", "-format", "ULMO", dmg,
        )
    run("hdiutil", "verify", "-quiet", dmg)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="HEAD", help="git ref of the app sources")
    ap.add_argument("--venv", type=Path, default=REPO / ".venv")
    ap.add_argument("--out", type=Path, default=REPO / "dist")
    ap.add_argument("--icon", type=Path, default=REPO / "packaging/AppIcon.icns")
    ap.add_argument("--no-dmg", action="store_true", help="stop after the .app")
    a = ap.parse_args()

    if not (SRC_FW / "Python").exists():
        sys.exit(f"python.org Python {PY_VER} framework not found at {SRC_FW}")
    venv_cfg = (a.venv / "pyvenv.cfg").read_text()
    if f"version = {PY_VER}." not in venv_cfg or str(SRC_FW) not in venv_cfg:
        sys.exit(f"{a.venv} is not a venv of {SRC_FW}")

    version = app_version(a.ref)
    a.out.mkdir(parents=True, exist_ok=True)
    app = a.out / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()

    log(f"{APP_NAME} {version} from {a.ref}")
    log("copying Python.framework")
    dst_ver = copy_framework(contents / "Frameworks/Python.framework")
    shutil.copy2(SRC_FW / "Resources/Python.app/Contents/MacOS/Python",
                 contents / "MacOS" / PY_EXE)

    log("relinking framework binaries")
    files = list(machos(dst_ver)) + [contents / "MacOS" / PY_EXE]
    changed = relink(files, dst_ver)
    stale = [p for p in files if any(str(SRC_FW) in d for d in deps(p)[1])]
    if stale:
        sys.exit(f"still linked to {SRC_FW}: {stale}")

    log("copying site-packages")
    copy_site_packages(a.venv, contents / "Resources/site-packages")
    log("copying app sources")
    copy_app_sources(a.ref, contents / "Resources/app")
    log("building WhisperFlowSysCap")
    build_helper(a.ref, contents / "MacOS/WhisperFlowSysCap")
    log("building JustVoiceTypeSettings")
    build_settings_helper(a.ref, contents / "MacOS/JustVoiceTypeSettings",
                          contents / "Resources/JustVoiceTypeSettings-Fonts")

    write_launcher(contents / "MacOS" / EXE)
    has_icon = a.icon.is_file()
    write_info_plist(contents / "Info.plist", version, has_icon)
    if has_icon:
        shutil.copy2(a.icon, contents / "Resources/AppIcon.icns")
    else:
        log(f"no icon at {a.icon} — the app gets the generic icon")

    log("signing (ad-hoc)")
    sign(app, dst_ver, changed)
    size = out("du", "-sh", app).split()[0]
    log(f"built {app} ({size})")

    if a.no_dmg:
        return
    dmg = a.out / f"JustVoiceType-{version}-arm64.dmg"
    log("creating DMG")
    make_dmg(app, dmg, version)
    digest = out("shasum", "-a", "256", dmg).split()[0]
    log(f"{dmg} ({out('du', '-h', dmg).split()[0]})  sha256 {digest}")


if __name__ == "__main__":
    main()
