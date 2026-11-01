"""Small helpers shared by the Windows installer modules (no Windows-only imports)."""

import hashlib
from pathlib import Path

GAME_FILES = ("HG.EXE", "HGSHELL.DLL", "HGSIM.DLL")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_disc1(source):
    if not str(source).strip():
        raise FileNotFoundError("Select the disc 1 drive or an extracted copy of it.")
    source = Path(source).expanduser()
    for candidate in (source, source / "HG-DISC-1"):
        if (candidate / "INSTALL" / "DATA" / "HG.EXE").is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Disc 1 source was not found under '{source}'. Select the disc root or a folder "
        "containing INSTALL\\DATA\\HG.EXE."
    )


def find_game_folder(folder):
    game = Path(folder).expanduser().resolve()
    missing = [name for name in GAME_FILES if not (game / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"'{game}' is not a complete Heavy Gear installation; missing "
            + ", ".join(missing)
            + "."
        )
    return game


def validate_x86_dll(path, label):
    """Raise ValueError unless `path` is a 32-bit (i386) Windows DLL image."""
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError(f"'{path}' is not a valid Windows executable image.")
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError(f"'{path}' has an invalid PE header.")
    machine = int.from_bytes(data[pe_offset + 4:pe_offset + 6], "little")
    characteristics = int.from_bytes(data[pe_offset + 22:pe_offset + 24], "little")
    if machine != 0x014C or not characteristics & 0x2000:
        raise ValueError(f"{label} must be a 32-bit Windows DLL.")
