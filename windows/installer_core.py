"""Windows installer operations shared by the standalone GUI and its smoke tests."""

import contextlib
import csv
import io
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _directory in (HERE, HERE.parent / "patcher"):
    if _directory.is_dir() and str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

import hg_controls
import hgfix
from hg_common import (  # noqa: F401  (re-exported for the GUI)
    GAME_FILES,
    find_disc1,
    find_game_folder,
    sha256_file,
    validate_x86_dll,
)
from win_system import install_system_components, register_official_patch_paths

RENDERER_NAME = "3dfx_hgd3d9.dll"
PATCH_FILENAMES = {"1.1": "hgp187d.exe", "1.2": "hgpatc12.exe"}


def bundled_path(name):
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / name
    return HERE.parent / "dist" / name


def ensure_game_not_running():
    if os.name != "nt":
        return
    tasklist = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32" / "tasklist.exe"
    try:
        result = subprocess.run(
            [str(tasklist), "/FI", "IMAGENAME eq HG.EXE", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise RuntimeError(f"Could not check whether Heavy Gear is running: {exc}") from exc
    if result.returncode:
        raise RuntimeError(
            f"Could not check whether Heavy Gear is running (tasklist exit code {result.returncode})."
        )
    for row in csv.reader(result.stdout.splitlines()):
        if row and row[0].casefold() == "hg.exe":
            raise RuntimeError("Exit Heavy Gear before applying fixes or updates.")


# --- copying the game ----------------------------------------------------------------------

def _copy_missing_files(source, destination):
    source = Path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        elif target.is_dir():
            raise IsADirectoryError(f"Expected a file at '{target}', but found a directory.")


def install_game(source, destination, controls="action", existing=False):
    destination = Path(destination).expanduser().resolve()
    if existing:
        find_game_folder(destination)
        if controls == "wasd":
            apply_controls(destination, "wasd")
        elif controls not in ("keep existing", "original"):
            raise ValueError("Existing installations support Keep existing or WASD controls.")
        return destination

    if controls not in ("action", "sim", "wasd"):
        raise ValueError(f"Unknown control layout: {controls}")
    disc = find_disc1(source)
    data = disc / "INSTALL" / "DATA"
    if (
        destination == disc
        or disc in destination.parents
        or destination == data
        or data in destination.parents
    ):
        raise ValueError("Choose an install folder outside the disc 1 source folder.")
    scheme = "ACTION" if controls == "wasd" else controls.upper()
    # The multi-language pressing has a set per language (ACTIONE/F/I/S, SIME/...) instead: the English one is
    # the same as ACTION/SIM of the English disc.
    control_source = next((data / name for name in (scheme, scheme + "E") if (data / name / "INPUTW.MAP").is_file()),
                          data / scheme)
    if not (control_source / "INPUTW.MAP").is_file():
        raise FileNotFoundError(f"The disc is missing the {controls} control files.")

    _copy_missing_files(data, destination)
    _copy_missing_files(control_source, destination)
    help_source = disc / "HELP"
    if help_source.is_dir():
        _copy_missing_files(help_source, destination / "HELP")
    find_game_folder(destination)
    if controls == "wasd":
        apply_controls(destination, "wasd")
    return destination


# --- the bundled patcher tools -------------------------------------------------------------

def _run_tool(main, args):
    """Run a patcher entry point in-process, returning what it printed."""
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            main(args)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            message = exc.code if isinstance(exc.code, str) else f"exit code {exc.code}"
            raise RuntimeError(f"The patcher stopped: {message}") from exc
    return output.getvalue().strip()


def apply_controls(game, layout):
    ensure_game_not_running()
    return _run_tool(hg_controls.main, [str(game), layout])


def _fps_argument(value):
    return f"{float(value):g}"


def apply_fixes(game, menu_fps=30, sim_fps=30, fixes=None, skipped=None, disc2=None, music_from=None,
                platform="windows"):
    """Run hgfix. `disc2` (the drive or a folder copy) is where the no-disc fix copies the VIDEO folder from;
    `music_from` is a folder of TRACKnn files for the music fix to copy into the game's MUSIC folder;
    `platform` picks hgfix's default fix set (the Linux apps pass "wine")."""
    ensure_game_not_running()
    args = [
        str(game),
        "--platform",
        platform,
        "--menu-fps",
        _fps_argument(menu_fps),
        "--sim-fps",
        _fps_argument(sim_fps),
    ]
    for name in fixes or ():
        args.extend(("--fix", name))
    for name in skipped or ():
        args.extend(("--skip", name))
    if disc2:
        args.extend(("--disc2", str(disc2)))
    if music_from:
        args.extend(("--music-from", str(music_from)))
    return _run_tool(hgfix.main, args)


def require_official_12(game):
    if hgfix.game_version(game) != "1.2":
        raise ValueError(
            "Direct3D 9 renderer requires the official 1.2 update, and this game isn't at 1.2."
        )


def install_renderer(game, renderer_path=None):
    ensure_game_not_running()
    game = find_game_folder(game)
    renderer = Path(renderer_path) if renderer_path else bundled_path(RENDERER_NAME)
    if not renderer.is_file():
        raise FileNotFoundError("The bundled Direct3D 9 renderer is missing from this installer.")
    validate_x86_dll(renderer, "The bundled Direct3D 9 renderer")
    plugin_dir = game / "PLUGIN"
    if not plugin_dir.is_dir():
        raise FileNotFoundError(f"Renderer plugin folder '{plugin_dir}' does not exist.")
    # The renderer was called hgrender before: take the old DLL out of the plugin list and keep its resolution.
    for old_name in OLD_RENDERER_NAMES:
        old_renderer = plugin_dir / old_name
        if old_renderer.exists():
            runs_dir = game / "hgd3d9-runs"
            runs_dir.mkdir(exist_ok=True)
            shutil.move(old_renderer, runs_dir / f"{old_name}.{datetime.now():%Y%m%d-%H%M%S-%f}.bak")
    old_res, new_res = game / "hgrender.res", game / "hgd3d9.res"
    if old_res.exists() and not new_res.exists():
        shutil.move(old_res, new_res)
    destination = plugin_dir / RENDERER_NAME
    if destination.exists() and sha256_file(destination) == sha256_file(renderer):
        return f"Direct3D 9 renderer is already installed in '{plugin_dir}'."
    if destination.exists():
        backup = destination.with_name(
            f"{destination.name}.{datetime.now():%Y%m%d-%H%M%S-%f}.bak"
        )
        shutil.copy2(destination, backup)
        os.chmod(destination, destination.stat().st_mode | stat.S_IWRITE)
    shutil.copy2(renderer, destination)
    return f"Installed Direct3D 9 renderer in '{plugin_dir}'."


# The Direct3D plugin the red-menu fix ("dx5draw") sets aside; a game still selecting it needs another renderer.
REMOVABLE_RENDERERS = ("dx5draw.dll",)
# The renderer's names before it was renamed hgd3d9.
OLD_RENDERER_NAMES = ("3dfx_hgrender.dll", "hgrender.dll")


def select_default_renderer(game):
    """Make the Direct3D 9 renderer the game's renderer after installing it, but only when nothing else is
    selected (or the selection is a plugin the red-menu fix takes away); an explicit choice of
    another renderer is left alone."""
    setting = Path(game) / "DLLFILE.INI"
    current = ""
    if setting.is_file():
        current = setting.read_text(encoding="ascii", errors="replace").strip().strip('"')
    if current and current.casefold() not in REMOVABLE_RENDERERS + OLD_RENDERER_NAMES:
        return f"Left the selected renderer ({current}) as it is."
    write_setting(setting, RENDERER_NAME)
    return "Selected Direct3D 9 renderer as the game's renderer."


# --- Glide driver (3DFXGEAR.DLL imports glide2x.dll) -----------------------------------------

GLIDE_NAME = "glide2x.dll"
GLIDE_REAL_NAME = "glide2x_real.dll"     # what the particle-fix proxy (tools/glidelog) loads
GLIDE_PROXY_MARK = b"glidelog attached"   # in every build of the proxy (its log line; CI checks for it too)


def find_glide_driver():
    """nGlide's installer puts its 32-bit glide2x.dll in SysWOW64 (System32 on 32-bit Windows). Returns the path or None."""
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    for folder in ("SysWOW64", "System32"):
        path = root / folder / GLIDE_NAME
        if path.is_file():
            try:
                validate_x86_dll(path, "The Glide driver")
            except (OSError, ValueError):
                continue
            return path
    return None


def install_glide_driver(game, driver, proxy=None):
    """Put a Glide driver (nGlide's or dgVoodoo2's glide2x.dll) in the game folder as glide2x_real.dll, and in front
    of it, as glide2x.dll (what 3DFXGEAR.DLL loads), the particle-fix proxy (tools/glidelog) this app carries, which
    loads the real driver under that name. `proxy` overrides the bundled one. Without a proxy (a checkout that has
    not built one) the driver goes in as glide2x.dll as well, and a proxy already in place (a glide2x.dll that
    differs from glide2x_real.dll) is kept. A file that is replaced is kept as a .bak copy first."""
    ensure_game_not_running()
    game = find_game_folder(game)
    driver = Path(driver)
    if driver.name.casefold() != GLIDE_NAME or not driver.is_file():
        raise FileNotFoundError("Choose a glide2x.dll (from nGlide or dgVoodoo2) for 3Dfx support.")
    validate_x86_dll(driver, "The Glide driver")
    if GLIDE_PROXY_MARK in driver.read_bytes():     # as glide2x_real.dll the proxy would load itself
        raise ValueError("That glide2x.dll is the particle-fix proxy, not a Glide driver. Choose the wrapper's own "
                         "glide2x.dll (nGlide's is in Windows' SysWOW64 folder).")
    proxy = Path(proxy) if proxy else bundled_path(GLIDE_NAME)
    if proxy.is_file():
        validate_x86_dll(proxy, "The particle-fix proxy")
    else:
        proxy = None
    front, real = game / GLIDE_NAME, game / GLIDE_REAL_NAME
    proxy_in_place = front.is_file() and real.is_file() and sha256_file(front) != sha256_file(real)
    if proxy_in_place and front.samefile(driver):
        raise ValueError("That glide2x.dll is the particle-fix proxy in the game folder. Choose the wrapper's own "
                         "glide2x.dll (nGlide's is in Windows' SysWOW64 folder).")
    plan = [(real, driver)]                    # the driver first: it may be read from the glide2x.dll replaced next
    if proxy:
        plan.append((front, proxy))
    elif not proxy_in_place:
        plan.append((front, driver))
    copied = []
    for target, source in plan:
        if target.is_file() and (target.samefile(source) or sha256_file(target) == sha256_file(source)):
            continue
        if target.exists():
            shutil.copy2(target, target.with_name(f"{target.name}.{datetime.now():%Y%m%d-%H%M%S-%f}.bak"))
            os.chmod(target, target.stat().st_mode | stat.S_IWRITE)
        shutil.copy2(source, target)
        copied.append(target.name)
    if not copied:
        return f"The Glide driver and particle fix in '{game}' are already up to date."
    if proxy:
        return (f"Installed the Glide driver as {GLIDE_REAL_NAME} and the particle-fix proxy as {GLIDE_NAME} in "
                f"'{game}' (updated: {', '.join(copied)}).")
    kept = " (the particle-fix proxy is kept)" if proxy_in_place else " (this copy of the app has no particle fix)"
    return f"Copied the Glide driver to {' and '.join(copied)} in '{game}'{kept}."


# --- the game's own renderer choice --------------------------------------------------------

# The shell's Graphics Type (its options screen) is saved as a number at this offset of hgsnd.cfg, and at every mission
# start the shell writes DLLFILE.INI and the sim's /3dfx option from it, so DLLFILE.INI alone does not stick. Found by
# switching it in the game (v1.2 on Windows 11, 2026-10-31): -1 = Software 640 (I76DRAW), otherwise the position among
# the plugins it lists, in the order Windows lists PLUGIN\*.dll: by name, ignoring case (3DFXGEAR before 3DFX_HGD3D9).
GRAPHICS_TYPE_FILE, GRAPHICS_TYPE_OFFSET = "hgsnd.cfg", 0x58
SOFTWARE_RENDERER = "i76draw.dll"
# Never in that list on a modern PC: the software renderer has its own entry, Rendition's needs its 1997 card.
UNLISTED_RENDERERS = (SOFTWARE_RENDERER, "renddraw.dll")


def listed_renderers(game):
    """The plugins in the order the game's Graphics Type lists them. 3DFXGEAR.DLL loads only with a Glide driver."""
    plugin_dir = Path(game) / "PLUGIN"
    if not plugin_dir.is_dir():
        return []
    glide = (Path(game) / GLIDE_NAME).is_file() or find_glide_driver() is not None
    names = sorted((path.name for path in plugin_dir.iterdir() if path.is_file() and path.suffix.lower() == ".dll"),
                   key=str.upper)
    return [name for name in names
            if name.casefold() not in UNLISTED_RENDERERS and (glide or name.casefold() != "3dfxgear.dll")]


def select_graphics_type(game, renderer):
    """Set the game's own Graphics Type to `renderer` (a PLUGIN file name), so the game keeps it. Returns a note for
    the log, or None when there is nothing to change (no hgsnd.cfg yet: the game reads DLLFILE.INI until its options
    are first saved)."""
    path = Path(game) / GRAPHICS_TYPE_FILE
    if not path.is_file():
        return None
    data = bytearray(path.read_bytes())
    if len(data) < GRAPHICS_TYPE_OFFSET + 4:
        return None
    if renderer.casefold() == SOFTWARE_RENDERER:
        index = -1
    else:
        listed = [name.casefold() for name in listed_renderers(game)]
        if renderer.casefold() not in listed:
            return f"{renderer} is not in the game's Graphics Type list here; choose it in the game's options instead."
        index = listed.index(renderer.casefold())
    value = index.to_bytes(4, "little", signed=True)
    if data[GRAPHICS_TYPE_OFFSET:GRAPHICS_TYPE_OFFSET + 4] == value:
        return None
    data[GRAPHICS_TYPE_OFFSET:GRAPHICS_TYPE_OFFSET + 4] = value
    backup_setting(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(bytes(data))
    os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
    os.replace(temporary, path)
    return f"The game's Graphics Type is set to {renderer} as well."


# --- renderer settings files ---------------------------------------------------------------

def backup_setting(path):
    backup = path.with_name(path.name + ".hglauncher.bak")
    if path.is_file() and not backup.exists():
        shutil.copy2(path, backup)


def write_setting(path, value):
    """Write a one-line settings file ("" deletes it, None leaves it), keeping a first backup."""
    if value is None:
        return
    backup_setting(path)
    if value == "":
        if path.exists():
            os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False
        ) as temporary:
            temporary.write(value.encode("ascii") + b"\r\n")
            temporary_path = Path(temporary.name)
        if path.exists():
            os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


# --- official patches ----------------------------------------------------------------------

def backup_game_files(game):
    game = find_game_folder(game)
    backup_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HeavyGearFixes" / "backups"
    backup = backup_root / f"HeavyGear-before-official-{datetime.now():%Y%m%d-%H%M%S-%f}"
    backup.mkdir(parents=True, exist_ok=False)
    for name in GAME_FILES:
        shutil.copy2(game / name, backup / name)
    return backup


def validate_patch(version, patch_path, game, disc1=None, expected_sha256=None):
    """Check an official patch can be run against `game`; returns its resolved path."""
    expected_name = PATCH_FILENAMES.get(version)
    if not expected_name:
        raise ValueError(f"Unsupported official update version: {version}.")
    patch = Path(patch_path).expanduser().resolve()
    if not patch.is_file():
        raise FileNotFoundError(f"Official {version} patch not found: '{patch}'.")
    if patch.name.casefold() != expected_name:
        raise ValueError(f"Official {version} patch must be named '{expected_name}'.")
    if expected_sha256 and sha256_file(patch) != expected_sha256:
        raise ValueError(f"'{patch}' changed after it was selected; select it again.")
    if version == "1.1":
        if not disc1:
            raise ValueError("The disc 1 source is required to validate the official 1.1 update.")
        data = find_disc1(disc1) / "INSTALL" / "DATA"
        for name in GAME_FILES:
            if sha256_file(game / name) != sha256_file(data / name):
                raise ValueError(
                    f"{name} is not the clean disc 1 version required by official 1.1."
                )
    return patch


def _patcher_detail(result, folder):
    """The patcher's own console text plus any RTPatch PATCH.ERR, appended to a failure message."""
    parts = [text.strip() for text in (result.stdout, result.stderr) if text and text.strip()]
    error_file = folder / "PATCH.ERR"
    if error_file.is_file():
        parts.append(error_file.read_text(errors="replace").strip())
    return ("\n" + "\n".join(parts)) if parts else ""


def is_complete_12(game, changed):
    """After the 1.2 patcher: it changed all three files, and the two DLLs on disk (not a .orig backup) are the 1.2
    build. HG.EXE has no place that tells 1.0 from 1.2, so for it the change has to do."""
    if set(changed) != set(GAME_FILES):
        return False
    try:
        return all(hgfix.detect(hgfix.PEFile(bytearray((Path(game) / name).read_bytes())), part)[0] == "1.2"
                   for name, part in (("HGSHELL.DLL", "shell"), ("HGSIM.DLL", "sim")))
    except (OSError, ValueError, IndexError, struct.error, SystemExit):
        return False


def _run_patcher(game, patch, version):
    before = {name: sha256_file(game / name) for name in GAME_FILES}
    # The bare exe: it is a GUI app with no console output (RTPatch's PATCH.ERR carries detail).
    # It waits, black, while any window is titled exactly "Heavy Gear" (see ui.TITLE).
    result = subprocess.run([str(patch)], cwd=patch.parent, check=False)
    detail = _patcher_detail(result, patch.parent)
    changed = [name for name in GAME_FILES if sha256_file(game / name) != before[name]]
    if not changed:
        raise RuntimeError(
            f"The official {version} patch did not change the game files (exit code "
            f"{result.returncode}). It may have been cancelled, may have refused the "
            "installed version recorded in HKLM\\Software\\Activision\\Heavy Gear (32-bit "
            "view), or may not have found the selected game installation." + detail
        )
    if result.returncode and version == "1.2" and is_complete_12(game, changed):
        # Seen on Windows 11: the 1.2 patcher reports 1 after patching every file (a second run then finds the
        # game at 1.2 and is skipped, which is why "install again" seemed to fix it).
        return (f"Official 1.2 patch changed: {', '.join(changed)} (the patcher reported exit code "
                f"{result.returncode}, but all three files are now the 1.2 build).")
    if result.returncode:
        raise RuntimeError(
            f"The official {version} patcher exited with code {result.returncode} after "
            f"changing {', '.join(changed)}. The game may be half-patched; restore the "
            "pre-update copy from the backup folder and try again." + detail
        )
    if version == "1.2" and hgfix.game_version(game) != "1.2":
        raise RuntimeError(
            "The official 1.2 patcher finished, but the game files are not a 1.2 build." + detail
        )
    return f"Official {version} patch changed: {', '.join(changed)}."


def _run_official_patches(game, config):
    patches = [tuple(entry) for entry in config.get("patches") or ()]
    if patches and hgfix.game_version(game) == "1.2":
        return ["The game is already at official 1.2; skipped the official updates."]
    validated = []
    for version, path, *rest in patches:
        validated.append(
            (version, validate_patch(version, path, game, config.get("disc1"), *rest))
        )
    if not validated:
        return []
    output = [f"Saved pre-update game files in: {backup_game_files(game)}"]
    for version, patch in validated:
        # Each patcher leaves junk-padded EXE/FTP values (and its own version subkey) that the
        # next one rejects, so re-register cleanly before every patcher.
        register_official_patch_paths(game, hgfix.game_version(game))
        output.append(_run_patcher(game, patch, version))
    return output


# --- operations (what the GUI asks for; run directly or in the elevated copy) ---------------

def _game(config):
    return find_game_folder(config["game"])


def _project_steps(game, config):
    output = []
    # The renderer goes first: the red-menu fix leaves the Direct3D plugin alone while it is selected.
    if config.get("install_renderer"):
        require_official_12(game)
        output.append(install_renderer(game))
        output.append(select_default_renderer(game))
    if config.get("glide_driver"):
        output.append(install_glide_driver(game, config["glide_driver"]))
    if config.get("apply_fixes"):
        output.append(
            apply_fixes(
                game, config["menu_fps"], config["sim_fps"], config["fixes"], config["skipped"],
                config.get("disc2"), config.get("music_from"),
            )
        )
    if config.get("install_media"):
        output.append(install_system_components(config["source"], config.get("codec_path")))
    return output


def _op_official(config):
    game = _game(config)
    ensure_game_not_running()
    return _run_official_patches(game, config) + _project_steps(game, config)


def _op_install(config):
    return [
        str(install_game(config["source"], config["game"], config["controls"], config["existing"]))
    ]


def _op_controls(config):
    return [apply_controls(_game(config), config["controls"])]


RENDERER_SETTINGS = ("DLLFILE.INI", "hgd3d9.res")


def _op_settings(config):
    game = _game(config)
    for filename, value in config["settings"].items():
        if filename not in RENDERER_SETTINGS:
            raise ValueError(f"Unsupported renderer setting: {filename}")
        write_setting(game / filename, value)
    note = select_graphics_type(game, config["settings"]["DLLFILE.INI"]) if config["settings"].get("DLLFILE.INI") else None
    return ["Renderer settings updated."] + ([note] if note else [])


def _op_fixes(config):
    return [
        apply_fixes(
            _game(config), config["menu_fps"], config["sim_fps"], config["fixes"], config["skipped"],
            config.get("disc2"), config.get("music_from"),
        )
    ]


def _op_renderer(config):
    game = _game(config)
    require_official_12(game)
    return [install_renderer(game), select_default_renderer(game)]


def _op_media(config):
    return [install_system_components(config["source"], config.get("codec_path"))]


OPERATIONS = {
    "official": _op_official,
    "install": _op_install,
    "controls": _op_controls,
    "settings": _op_settings,
    "fixes": _op_fixes,
    "renderer": _op_renderer,
    "project": lambda config: _project_steps(_game(config), config),
    "media": _op_media,
}


def run_privileged_operation(config):
    name = config.get("operation", "official")
    handler = OPERATIONS.get(name)
    if handler is None:
        raise ValueError(f"Unknown elevated operation: {name}")
    return "\n".join(part for part in handler(config) if part)
