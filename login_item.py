"""Запуск Just Voice Type при входе в систему через LaunchAgent.

Агент запускает сам .app через `open -a`, поэтому разрешения macOS
остаются за бандлом. AssociatedBundleIdentifiers показывает в «Объектах
входа» имя приложения, а не безликий `open`. Включение только пишет
plist: launchd подхватит его при следующем входе. Работает лишь для
установленного приложения; при запуске из исходников — install_autostart.sh.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from typing import Callable, Optional

LABEL = "com.justvoicetype.app"


def plist_path(home: Optional[str] = None) -> str:
    home = home or os.path.expanduser("~")
    return os.path.join(home, "Library", "LaunchAgents", f"{LABEL}.plist")


def app_bundle_path(executable: Optional[str] = None) -> Optional[str]:
    """Путь к .app, внутри которого работает интерпретатор, или None."""
    exe = os.path.abspath(executable or sys.executable)
    marker = ".app/Contents/"
    i = exe.find(marker)
    return exe[: i + len(".app")] if i >= 0 else None


def bundle_id(app_path: str) -> str:
    try:
        with open(os.path.join(app_path, "Contents", "Info.plist"), "rb") as f:
            return str(plistlib.load(f).get("CFBundleIdentifier") or LABEL)
    except (OSError, plistlib.InvalidFileException):
        return LABEL


def render_plist(app_path: str, bid: str) -> bytes:
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/open", "-a", app_path],
        "RunAtLoad": True,
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "AssociatedBundleIdentifiers": [bid],
    })


def is_enabled(app_path: Optional[str], home: Optional[str] = None) -> bool:
    if not app_path:
        return False
    try:
        with open(plist_path(home), "rb") as f:
            args = plistlib.load(f).get("ProgramArguments") or []
    except (OSError, plistlib.InvalidFileException):
        return False
    return bool(args) and args[-1] == app_path


def enable(app_path: str, home: Optional[str] = None) -> Optional[str]:
    """None — готово, иначе текст ошибки для лога."""
    path = plist_path(home)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(render_plist(app_path, bundle_id(app_path)))
        os.replace(tmp, path)
    except OSError as e:
        return str(e)
    return None


def disable(
    home: Optional[str] = None,
    run: Callable = subprocess.run,
) -> Optional[str]:
    # агент мог быть загружен (после входа) — выгружаем, ошибки не важны
    try:
        run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, timeout=5)
    except Exception:
        pass
    try:
        os.remove(plist_path(home))
    except FileNotFoundError:
        pass
    except OSError as e:
        return str(e)
    return None
