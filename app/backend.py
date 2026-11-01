"""The app's back-end interface and what both platforms share (no window code).

The window (ui.py) only talks to a back end: it hands over the player's choices as a plain dict and gets back
plans, game descriptions and player-facing errors (ValueError, FileNotFoundError, RuntimeError). The two back
ends wrap the existing cores in windows/ and linux/; this module puts those folders on sys.path."""

import os
import sys
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(getattr(sys, "_MEIPASS", HERE.parent))
for _directory in (ROOT / "windows", ROOT / "patcher", ROOT / "linux"):
    if _directory.is_dir() and str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

import hgfix  # noqa: E402
import installer_core  # noqa: E402
import launcher_settings  # noqa: E402
from hg_gui_common import (  # noqa: E402
    HG_RENDERER,
    list_renderers,
    read_selected_renderer,
    validate_resolution,
)

# --- the fixes the app offers -------------------------------------------------------------------

Fix = namedtuple("Fix", "name label description default section")

# One label and one-line description per fix the app can offer (what the fixes do is hgfix's business).
LABELS = {
    "limiter": ("Frame-rate limiter",
                "Holds menus and missions to the frame rates chosen on the Play page."),
    "display": ("Display mode after missions",
                "Keeps the 256-colour mode after missions and switches to desktop mode before movies."),
    "dx5draw": ("Red-menu fix",
                "Sets the game's own Direct3D plugin (DX5DRAW) aside, so the menus are not red after a "
                "mission. That renderer is then not offered."),
    "anet2": ("Mission-start fix",
              "Keeps ANET2.DLL loaded, which avoids the official 1.2 freeze when a mission starts."),
    "moviebg": ("Movies with the Direct3D 9 renderer",
                "Keeps the black movie backdrop hidden, so movies show without a Wine virtual desktop."),
    "movie32": ("Movie crash fix",
                "Movie screens ask for 32-bit colour instead of 16-bit, which avoids a crash around movies."),
    "partdepth": ("Particle depth (official 1.2)",
                  "Smoke and explosions get their real depth, so renderers with a depth buffer hide them "
                  "behind terrain."),
    "nodisc": ("Copy the cutscenes (about 180 MB) so the game does not look for disc 2",
               "Cutscenes are read from the game's VIDEO folder."),
    "music": ("Rip the music from the disc's audio tracks (several hundred MB of WAV files)",
              "The soundtrack plays from the game's MUSIC folder instead of the CD."),
    "borderless": ("Borderless full screen (official 1.2)",
                   "Menus, movies and missions in one borderless window the size of the desktop, scaled, with "
                   "no display-mode switches. Replaces the display and movie backdrop fixes."),
}
# Per hgfix platform. palette (experimental) and glide (retired) are never offered. Every offered fix is
# shown as a plain box on the Fixes page; the disc 2 section on the Install page only supplies the paths.
OFFERED = {
    "wine": ("limiter", "display", "anet2", "moviebg", "partdepth", "borderless"),
    "windows": ("limiter", "dx5draw", "anet2", "movie32", "partdepth", "nodisc", "music", "borderless"),
}
# Fixes the disc 2 section on the Install page supplies paths for (the box itself is on the Fixes page).
DISC2_FIXES = ("nodisc", "music")


def fixes(platform, version=None):
    """The fixes offered on an hgfix platform ("wine" or "windows"), defaults from the patcher.
    `version` ("1.0"/"1.2") lets the v1.2-only fixes default on for a 1.2 game."""
    on = hgfix.choose_fixes(platform, [], [], version)
    return [
        Fix(name, *LABELS[name], name in on, "fixes")
        for name in OFFERED[platform]
    ]


# --- shared helpers ------------------------------------------------------------------------------

def frozen():
    return bool(getattr(sys, "frozen", False))


def search_roots():
    """Where to look for disc copies and patch files: beside the app (or the checkout), then the current folder."""
    roots = [Path(sys.executable).resolve().parent if frozen() else HERE.parent, Path.cwd()]
    return [root for index, root in enumerate(roots) if root not in roots[:index]]


def find_adjacent(candidates, test):
    """The first candidate path (as text) that passes test, or ''."""
    for candidate in candidates:
        try:
            if test(candidate):
                return str(candidate)
        except OSError:
            pass
    return ""


def find_adjacent_patch(version):
    """An official patch file beside the app, or ''."""
    name = installer_core.PATCH_FILENAMES[version]
    folder = Path(name).stem
    return find_adjacent(
        [
            root / sub / file
            for root in search_roots()
            for sub in ("", Path("patches") / folder, "patches")
            for file in (name, name.upper())
        ],
        Path.is_file,
    )


def passes(check, value):
    try:
        check(value)
        return True
    except (OSError, ValueError):
        return False


def has_game(game):
    return all(hgfix.find_file(str(game), name) for name in installer_core.GAME_FILES)


def installed_version(game):
    """The official version ('1.0'/'1.2') of an installed game, or None when there is none."""
    return hgfix.game_version(str(game)) if has_game(game) else None


GameInfo = namedtuple("GameInfo", "location game found version renderer renderers resolution")


class Backend:
    """What the window needs from a platform. Subclasses fill in the platform parts."""

    name = ""              # "windows" or "linux"
    platform = ""          # hgfix's platform name
    can_stop = False       # whether a started game can be stopped from the app
    location_label = ""
    location_title = ""    # the folder picker's title
    patch_note = ""        # what running the official patchers involves here
    install_sections = ()  # platform-only parts of the Install page, by name (ui.py builds them)
    disc_images = False    # the disc fields also take a .iso, mounted at Install / Update
    play_sections = ()
    extra_pages = ()
    settings_extra = ()    # launcher.json keys this platform keeps besides the shared ones

    # --- settings ---------------------------------------------------------------------------
    def fixes(self, version=None):
        return fixes(self.platform, version)

    def load_settings(self):
        return launcher_settings.load_settings(
            [fix.name for fix in self.fixes()], extra=self.settings_extra
        )

    def initial_choices(self, saved):
        """Every choice the window shows, from the saved settings and what can be found."""
        location = self.default_location(saved)
        version = installed_version(self.game_folder(location))
        return {
            "location": location,
            "menu_fps": saved.get("menu_fps", "30"),
            "sim_fps": saved.get("sim_fps", "30"),
            "fixes": {fix.name: saved.get("fixes", {}).get(fix.name, fix.default) for fix in self.fixes(version)},
            "controls": "keep existing" if has_game(self.game_folder(location)) else "action",
            "apply11": False,
            "apply12": False,
            "patch11": find_adjacent_patch("1.1"),
            "patch12": find_adjacent_patch("1.2"),
            "apply_fixes": True,
            # On by default, but only where it can work: a run that does not reach 1.2 skips it until the
            # player ticks the box themselves (renderer_touched).
            "install_renderer": True,
            "renderer_touched": False,
            "renderer": "",
            "resolution": "",
        }

    def settings_to_save(self, choices):
        return {
            "game_path": str(self.game_folder(choices["location"])),
            "menu_fps": choices["menu_fps"],
            "sim_fps": choices["sim_fps"],
            "fixes": dict(choices["fixes"]),
            **{key: choices[key] for key in self.settings_extra if key in choices},
        }

    def save_settings(self, choices):
        return launcher_settings.save_settings(self.settings_to_save(choices))

    # --- the game ---------------------------------------------------------------------------
    def game_folder(self, location):
        """The folder holding HG.EXE for a location (the location itself on Windows)."""
        raise NotImplementedError

    def default_location(self, saved):
        raise NotImplementedError

    def find_game(self, saved=None):
        """The location of an installed game, or None."""
        raise NotImplementedError

    def describe_game(self, location):
        game = self.game_folder(location) if str(location).strip() else None
        if not game or not has_game(game):
            return GameInfo(location, game, False, None, "", [], "")
        resolution = ""
        res = hgfix.find_file(str(game), "hgd3d9.res")
        if res:
            try:
                resolution = Path(res).read_text(encoding="ascii").strip()
            except (OSError, UnicodeError):
                resolution = ""
        return GameInfo(
            location, game, True, hgfix.game_version(str(game)), read_selected_renderer(game),
            list_renderers(game), resolution,
        )

    def check_path(self, field, value):
        """(ok, note) for a path field: ok is None for an empty field, else whether the path is usable."""
        value = str(value).strip()
        if not value:
            return None, ""
        check = self.path_checks().get(field)
        if check is None:
            return None, ""
        try:
            check(value)
        except (OSError, ValueError) as exc:
            return False, f"Not found: {exc}"
        return True, "Found"

    def path_checks(self):
        def patch(version):
            def check(value):
                path = Path(value).expanduser()
                if not path.is_file():
                    raise FileNotFoundError("no file there.")
                expected = installer_core.PATCH_FILENAMES[version]
                if path.name.casefold() != expected:
                    raise ValueError(f"the official patch is named '{expected}'.")
            return check

        return {
            "disc1": installer_core.find_disc1,
            "patch11": patch("1.1"),
            "patch12": patch("1.2"),
        }

    def missing_programs(self, choices):
        """Lines naming programs the chosen options need but this system lacks."""
        return []

    def describe_error(self, exc):
        return str(exc) or exc.__class__.__name__

    # --- play -------------------------------------------------------------------------------
    def validate_game(self, choices):
        game = self.game_folder(choices["location"])
        if not hgfix.find_file(str(game), "HG.EXE"):
            raise FileNotFoundError(f"HG.EXE was not found in '{game}'.")
        if not hgfix.find_file(str(game), "HGSHELL.DLL") or not hgfix.find_file(str(game), "HGSIM.DLL"):
            raise FileNotFoundError(f"'{game}' is missing HGSHELL.DLL or HGSIM.DLL.")
        if choices["menu_fps"] not in ("30", "60") or choices["sim_fps"] not in ("30", "60"):
            raise ValueError("Choose 30 or 60 FPS for both menus and simulation.")
        return game

    def plan_apply(self, choices):
        """Check the Play page's choices and return what apply() and play() need."""
        game = self.validate_game(choices)
        renderer = choices.get("renderer") or ""
        if renderer and not hgfix.find_file(str(game), f"PLUGIN/{renderer}"):
            raise FileNotFoundError(f"The selected renderer is no longer installed: {renderer}")
        settings = {}
        if renderer:
            settings["DLLFILE.INI"] = renderer
            if renderer.casefold() == HG_RENDERER:
                settings["hgd3d9.res"] = validate_resolution(choices.get("resolution", ""))
        fixes = dict(choices["fixes"])
        if fixes.get("dx5draw") and renderer.casefold() == "dx5draw.dll":
            raise ValueError(
                "The Direct3D renderer plugin (DX5DRAW.DLL) is selected as the renderer, so it "
                "can't be turned off. Choose another renderer, or untick the red-menu fix."
            )
        return {
            "game": game,
            "menu_fps": choices["menu_fps"],
            "sim_fps": choices["sim_fps"],
            "fixes": fixes,
            "renderer_settings": settings,
        }

    def plan_play(self, choices):
        """Check the game for Play without changes."""
        return {"game": self.validate_game(choices)}

    def apply(self, plan, report):
        raise NotImplementedError

    def play(self, plan, report, on_process=None):
        raise NotImplementedError

    def stop(self):
        pass

    # --- install ----------------------------------------------------------------------------
    def validate_install(self, choices):
        raise NotImplementedError

    def run_install(self, config, report, on_process=None):
        """Run a validated install; returns (finish message, game folder)."""
        raise NotImplementedError

    def cancel_install(self, config):
        """A validated install the player did not start after all: undo what validate_install set up."""


def fix_lists(fixes):
    """{name: bool} -> (selected, unselected) name lists for hgfix."""
    return (
        [name for name, enabled in fixes.items() if enabled],
        [name for name, enabled in fixes.items() if not enabled],
    )


def apply_fixes(game, plan, platform):
    selected, skipped = fix_lists(plan["fixes"])
    return installer_core.apply_fixes(
        game, plan["menu_fps"], plan["sim_fps"], selected, skipped, platform=platform
    ) or "Community fixes applied."


def for_this_platform():
    """The back end for the running system."""
    if os.name == "nt":
        from backend_windows import WindowsBackend

        return WindowsBackend()
    from backend_linux import LinuxBackend

    return LinuxBackend()
