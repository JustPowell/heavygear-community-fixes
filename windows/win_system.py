"""Machine-wide changes the game's cutscenes and official patchers need: registry entries,
the Indeo 5 codec and the game fonts. Everything here is additive: a differing existing file or
registry value is reported and left alone, and a failed install undoes what it did."""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hg_common import find_disc1, find_game_folder, sha256_file, validate_x86_dll

CODEC_NAME = "ir50_32.dll"


# --- official patcher registration ---------------------------------------------------------

def registration_conflict(existing, game):
    """Return the other install `existing` (an App Paths HG.EXE value) points at, or None."""
    if not existing:
        return None
    wanted = os.path.normcase(os.path.normpath(str(Path(game) / "HG.EXE")))
    found = os.path.normcase(os.path.normpath(existing))
    if found == wanted or not Path(existing).is_file():
        return None  # same install, or a stale entry for a game that no longer exists
    return existing


def stale_version_subkeys(subkeys, game_version):
    """Version subkeys of the Activision key that claim a newer game than `game_version`.

    The official patchers read the lowest subkey as the installed version, so a leftover
    "1.2" from an earlier install makes the 1.1 patcher refuse a clean 1.0 game."""
    if game_version != "1.0":
        return []  # only a clean disc install is known well enough to correct
    stale = []
    for name in subkeys:
        try:
            if float(name) > 1.0:
                stale.append(name)
        except ValueError:
            continue
    return stale


def _query(key, name):
    import winreg

    try:
        return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def register_official_patch_paths(game, game_version=None):
    """Create the registry entries the official patchers look for.

    Values that already exist are kept, except version subkeys that contradict the game's real
    version (`game_version`, as reported by hgfix.game_version)."""
    import winreg

    game = find_game_folder(game)
    root = winreg.HKEY_LOCAL_MACHINE
    wow64 = getattr(winreg, "KEY_WOW64_32KEY", 0)
    access = winreg.KEY_READ | winreg.KEY_WRITE | wow64
    app_paths_name = r"Software\Microsoft\Windows\CurrentVersion\App Paths\HG.EXE"
    try:
        with winreg.OpenKeyEx(root, app_paths_name, 0, winreg.KEY_READ | wow64) as existing_key:
            other = registration_conflict(_query(existing_key, None), game)
    except FileNotFoundError:
        other = None
    if other:
        raise FileExistsError(
            f"Heavy Gear is already registered at '{other}'. Choose that folder as the "
            "existing installation, or uninstall that copy first; the official patcher "
            "would otherwise patch the registered copy instead of this one."
        )
    with winreg.CreateKeyEx(root, r"Software\Activision\Heavy Gear", 0, access) as activision:
        # Always rewrite EXE/FTP, keeping any existing value (e.g. another SKU). A patcher run
        # leaves them as 260-character buffers padded with junk after the terminator, which the
        # next official patcher then rejects as "not properly installed".
        for name, default in (("EXE", "HG.EXE"), ("FTP", "HGEARW95")):
            value = (_query(activision, name) or "").split("\0")[0].strip() or default
            winreg.SetValueEx(activision, name, 0, winreg.REG_SZ, value)
        subkeys = [winreg.EnumKey(activision, i) for i in range(winreg.QueryInfoKey(activision)[0])]
        for name in stale_version_subkeys(subkeys, game_version):
            winreg.DeleteKeyEx(activision, name, wow64, 0)
        if game_version == "1.0" or not winreg.QueryInfoKey(activision)[0]:
            winreg.CreateKeyEx(activision, "1.00", 0, access).Close()
    with winreg.CreateKeyEx(root, app_paths_name, 0, access) as app_paths:
        winreg.SetValueEx(app_paths, None, 0, winreg.REG_SZ, str(game / "HG.EXE"))
        winreg.SetValueEx(app_paths, "Path", 0, winreg.REG_SZ, str(game))


def registered_game_folder():
    """The folder the retail installer or an official patch registered, if it still exists."""
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\Microsoft\Windows\CurrentVersion\App Paths\HG.EXE",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
        ) as key:
            folder = _query(key, "Path")
    except OSError:
        return None
    if folder and (Path(folder) / "HG.EXE").is_file():
        return Path(folder)
    return None


# --- TrueType names ------------------------------------------------------------------------

def _name_records(path):
    """{name id: [(is_english, text)]} from a TrueType font's name table."""
    data = Path(path).read_bytes()
    if len(data) < 12:
        raise ValueError(f"'{path}' is not a valid TrueType font.")
    name_offset = name_length = None
    for index in range(int.from_bytes(data[4:6], "big")):
        record = 12 + index * 16
        if data[record:record + 4] == b"name":
            name_offset = int.from_bytes(data[record + 8:record + 12], "big")
            name_length = int.from_bytes(data[record + 12:record + 16], "big")
            break
    if name_offset is None or name_offset + name_length > len(data):
        raise ValueError(f"'{path}' has no valid font name table.")
    table = data[name_offset:name_offset + name_length]
    strings = int.from_bytes(table[4:6], "big")
    names = {}
    for index in range(int.from_bytes(table[2:4], "big")):
        record = 6 + index * 12
        if record + 12 > len(table):
            break
        platform = int.from_bytes(table[record:record + 2], "big")
        language = int.from_bytes(table[record + 4:record + 6], "big")
        name_id = int.from_bytes(table[record + 6:record + 8], "big")
        length = int.from_bytes(table[record + 8:record + 10], "big")
        offset = int.from_bytes(table[record + 10:record + 12], "big")
        if strings + offset + length > len(table):
            continue
        raw = table[strings + offset:strings + offset + length]
        try:
            text = raw.decode("utf-16-be" if platform in (0, 3) else "mac_roman").strip("\0 ")
        except UnicodeError:
            continue
        if text:
            names.setdefault(name_id, []).append((language == 0x0409, text))
    return names


def _best(names, *name_ids):
    for name_id in name_ids:
        if name_id in names:
            return sorted(names[name_id], key=lambda item: item[0], reverse=True)[0][1]
    return None


def font_family(path):
    family = _best(_name_records(path), 16, 1)
    if not family:
        raise ValueError(f"Could not read the family name from '{path}'.")
    return family


def font_registry_name(path):
    """The value name Windows lists the font under: its full name, e.g. 'Foo Bold Italic'."""
    names = _name_records(path)
    full = _best(names, 4)
    if not full:
        family, style = _best(names, 1), _best(names, 2)
        if not family:
            raise ValueError(f"Could not read the font name from '{path}'.")
        full = family if not style or style.casefold() == "regular" else f"{family} {style}"
    return f"{full} (TrueType)"


def plan_font_installs(fonts, font_dir, registered):
    """Check every font before touching the machine.

    `registered` maps each planned registry value name to the file it currently names (or
    None). Returns [(source, destination, registry value name)].
    """
    plan, seen = [], {}
    for font in fonts:
        entry = font_registry_name(font)
        if entry.casefold() in seen:
            raise ValueError(
                f"'{font.name}' and '{seen[entry.casefold()]}' have the same font name '{entry}'."
            )
        seen[entry.casefold()] = font.name
        destination = Path(font_dir) / font.name
        if destination.exists() and sha256_file(font) != sha256_file(destination):
            raise FileExistsError(f"Refusing to replace the different font '{destination}'.")
        current = registered.get(entry)
        if current and current.casefold() != font.name.casefold():
            raise FileExistsError(f"Font '{entry}' is already registered as '{current}'.")
        plan.append((font, destination, entry))
    return plan


# --- Indeo 5 and fonts ---------------------------------------------------------------------

def _system_directory():
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    return windows / ("SysWOW64" if sys.maxsize > 2**32 else "System32")


def indeo_installed():
    """Windows already has the 32-bit Indeo 5 codec the cutscenes need."""
    return (_system_directory() / CODEC_NAME).is_file()


def _unshield_codec(source, workdir):
    """Extract ir50_32.dll from disc 1's installer cabinet (INSTALL\\DATA1.CAB) into workdir with unshield."""
    install = find_disc1(source) / "INSTALL"
    cabinet = next((item for item in install.iterdir() if item.name.casefold() == "data1.cab"), None)
    if cabinet is None:
        raise FileNotFoundError(f"The Indeo codec cabinet was not found at '{install / 'DATA1.CAB'}'.")
    subprocess.run(
        [shutil.which("unshield"), "-d", str(workdir), "x", str(cabinet)],
        capture_output=True, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    codec = next((item for item in Path(workdir).rglob("*") if item.name.casefold() == CODEC_NAME), None)
    if codec is None:
        raise FileNotFoundError("unshield did not find ir50_32.dll in disc 1's installer cabinet.")
    validate_x86_dll(codec, "The Indeo codec")
    return codec


def resolve_indeo_codec(codec_path=None, source=None, workdir=None):
    """The Indeo 5 codec to install: the one Windows already has, else one extracted from disc 1 (`source`) with
    unshield into `workdir` (a new temporary folder when None), else (or when that fails) the extracted file the
    player selected."""
    installed = _system_directory() / CODEC_NAME
    if installed.is_file():
        return installed
    if source and shutil.which("unshield"):
        try:
            return _unshield_codec(source, workdir or tempfile.mkdtemp(prefix="hg-indeo-"))
        except (OSError, ValueError):
            if not codec_path:
                raise
    if codec_path:
        codec = Path(codec_path).expanduser().resolve()
        if codec.name.casefold() != CODEC_NAME or not codec.is_file():
            raise ValueError("Choose an extracted ir50_32.dll file for Indeo support.")
        return codec
    raise FileNotFoundError(
        "The Indeo codec is not installed. Install unshield and add it to PATH to extract it from disc 1, "
        "or choose an extracted ir50_32.dll."
    )


def install_system_components(source, codec_path=None):
    """Install the game's fonts and the Indeo 5 codec (needs administrator rights)."""
    disc = find_disc1(source)
    fonts = sorted((disc / "INSTALL").glob("*.TTF"))
    if not fonts:
        raise FileNotFoundError("No game fonts (*.TTF) were found on disc 1.")
    with tempfile.TemporaryDirectory(prefix="hg-indeo-") as workdir:
        return _install_system_components(fonts, resolve_indeo_codec(codec_path, source, workdir))


def _install_system_components(fonts, codec):
    import winreg

    validate_x86_dll(codec, "The Indeo codec")
    codec_destination = _system_directory() / CODEC_NAME
    if codec.resolve() != codec_destination.resolve() and codec_destination.exists():
        if sha256_file(codec) != sha256_file(codec_destination):
            raise FileExistsError(
                f"Refusing to replace the different system codec '{codec_destination}'."
            )
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    font_view = getattr(winreg, "KEY_WOW64_64KEY", 0) if sys.maxsize > 2**32 else 0
    drivers_path = r"Software\Microsoft\Windows NT\CurrentVersion\Drivers32"
    fonts_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    machine = winreg.HKEY_LOCAL_MACHINE

    # Validate everything first so a conflict cannot leave a half-installed system.
    with winreg.OpenKeyEx(machine, drivers_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
        registered = _query(key, "vidc.iv50")
    if registered and registered.casefold() != CODEC_NAME:
        raise FileExistsError(
            f"Indeo IV50 is already registered as '{registered}'; refusing to replace it."
        )
    with winreg.OpenKeyEx(machine, fonts_path, 0, winreg.KEY_READ | font_view) as key:
        names = [font_registry_name(font) for font in fonts]
        current_fonts = {name: _query(key, name) for name in names}
        plan = plan_font_installs(fonts, font_dir, current_fonts)
        registered_fonts = {name for name, value in current_fonts.items() if value}

    copied_files, set_values = [], []
    try:
        if not codec_destination.exists():
            shutil.copy2(codec, codec_destination)
            copied_files.append(codec_destination)
        for font, destination, _entry in plan:
            if not destination.exists():
                shutil.copy2(font, destination)
                copied_files.append(destination)
        access = winreg.KEY_WRITE
        if registered is None:  # only ask for write access when something must change
            with winreg.CreateKeyEx(
                machine, drivers_path, 0, access | winreg.KEY_WOW64_32KEY
            ) as key:
                winreg.SetValueEx(key, "vidc.iv50", 0, winreg.REG_SZ, CODEC_NAME)
                set_values.append((drivers_path, winreg.KEY_WOW64_32KEY, "vidc.iv50"))
        missing_fonts = [item for item in plan if item[2] not in registered_fonts]
        if missing_fonts:
            with winreg.CreateKeyEx(machine, fonts_path, 0, access | font_view) as key:
                for font, _destination, entry in missing_fonts:
                    winreg.SetValueEx(key, entry, 0, winreg.REG_SZ, font.name)
                    set_values.append((fonts_path, font_view, entry))
        _load_fonts([destination for _font, destination, _entry in plan])
    except BaseException:
        _undo(machine, copied_files, set_values)
        raise
    return f"Installed Indeo 5 and {len(fonts)} game font(s)."


def _undo(machine, copied_files, set_values):
    import winreg

    for path, view, name in reversed(set_values):
        try:
            with winreg.OpenKeyEx(machine, path, 0, winreg.KEY_SET_VALUE | view) as key:
                winreg.DeleteValue(key, name)
        except OSError:
            pass
    for path in reversed(copied_files):
        try:
            path.unlink()
        except OSError:
            pass


def _load_fonts(destinations):
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    add_font = gdi32.AddFontResourceW
    add_font.argtypes = [ctypes.c_wchar_p]
    add_font.restype = ctypes.c_int
    for destination in destinations:
        if not add_font(str(destination)):
            raise OSError(f"Windows could not load the game font '{destination.name}'.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send_message_timeout = user32.SendMessageTimeoutW
    send_message_timeout.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    send_message_timeout.restype = ctypes.c_int
    result = ctypes.c_size_t()
    send_message_timeout(0xFFFF, 0x001D, 0, 0, 0x0002, 5000, ctypes.byref(result))
