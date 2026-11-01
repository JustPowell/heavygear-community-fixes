"""Pieces the app's back ends share (kept free of any window code)."""

import os
import re
import sys
from pathlib import Path

import hgfix
import win_elevation
import win_system

HG_RENDERER = "3dfx_hgd3d9.dll"


RESOLUTION_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$", re.IGNORECASE)


def validate_resolution(value):
    value = value.strip()
    if not value:
        return ""
    match = RESOLUTION_RE.fullmatch(value)
    if not match:
        raise ValueError("Resolution must be WIDTHxHEIGHT, for example 1920x1080.")
    width, height = (int(part) for part in match.groups())
    if not (320 <= width <= 7680 and 240 <= height <= 4320):
        raise ValueError("Resolution must be between 320x240 and 7680x4320.")
    return f"{width}x{height}"


def read_selected_renderer(game):
    setting = hgfix.find_file(game, "DLLFILE.INI")
    if not setting:
        return ""
    return Path(setting).read_text(encoding="ascii", errors="replace").strip().strip('"')


# Rendition's RRedline renderer needs a 1997 Rendition Verite card: never usable today, so not offered.
UNUSABLE_RENDERERS = ("renddraw.dll",)


def list_renderers(game):
    plugin_dir = hgfix.find_file(game, "PLUGIN")
    if not plugin_dir or not Path(plugin_dir).is_dir():
        return []
    return sorted(
        (path.name for path in Path(plugin_dir).iterdir()
         if path.is_file() and path.suffix.lower() == ".dll" and path.name.casefold() not in UNUSABLE_RENDERERS),
        key=str.casefold,
    )


def get_game_path_from_registry():
    if os.name != "nt":
        return None
    registered = win_system.registered_game_folder()
    if registered:
        return registered
    import winreg

    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        root = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY
        )
    except OSError:
        return None
    with root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            try:
                name = winreg.EnumKey(root, index)
                with winreg.OpenKey(root, name) as entry:
                    display_name = winreg.QueryValueEx(entry, "DisplayName")[0]
                    if "heavy gear" not in str(display_name).lower():
                        continue
                    install_path = winreg.QueryValueEx(entry, "InstallLocation")[0]
                    if install_path and (Path(install_path) / "HG.EXE").is_file():
                        return Path(install_path)
            except OSError:
                continue
    return None


def run_elevated_config(config):
    return win_elevation.run_elevated(config)


def ensure_standard_streams():
    """A --windowed PyInstaller exe has no stdout/stderr; give stray prints somewhere to go."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def enable_dpi_awareness():
    """Render sharply on high-DPI displays instead of being bitmap-scaled (best effort)."""
    if os.name != "nt":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
