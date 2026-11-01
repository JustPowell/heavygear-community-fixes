"""Remember the launcher's choices between runs (per user, outside the game folder)."""

import json
import os
import tempfile
from pathlib import Path

FPS_CHOICES = ("30", "60")


def settings_path():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "HeavyGearFixes" / "launcher.json"


def load_settings(fix_names, path=None, extra=()):
    """Saved settings, or {} for anything missing, unreadable, or not valid."""
    try:
        with open(path or settings_path(), encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    settings = {}
    if isinstance(raw.get("game_path"), str) and raw["game_path"].strip():
        settings["game_path"] = raw["game_path"]
    for key in ("menu_fps", "sim_fps"):
        if raw.get(key) in FPS_CHOICES:
            settings[key] = raw[key]
    for key in extra:
        if isinstance(raw.get(key), str):
            settings[key] = raw[key]
    if isinstance(raw.get("fixes"), dict):
        settings["fixes"] = {
            name: value
            for name, value in raw["fixes"].items()
            if name in fix_names and isinstance(value, bool)
        }
    return settings


def save_settings(settings, path=None):
    """Best effort: a launcher that can't remember its choices must still work."""
    path = Path(path or settings_path())
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(settings, stream, indent=2)
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        if temporary and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
