"""Linux helpers for the app's Linux back end (no window code).

The app wraps the shell scripts in this folder; this module runs them, finds what they need,
and maps the window's choices to the environment variables the scripts read."""

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(getattr(sys, "_MEIPASS", HERE.parent))
for _directory in (HERE, ROOT / "windows", ROOT / "patcher", HERE.parent / "windows", HERE.parent / "patcher"):
    if _directory.is_dir() and str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

import hgfix  # noqa: E402

SCRIPTS = ROOT / "linux"
HOME_DIR = Path.home() / "Games" / "HeavyGear"
SCALE_CHOICES = ("integer", "fit", "stretch", "fill")
FILTER_CHOICES = ("nearest", "linear", "fsr", "nis", "pixel")


def frozen():
    return bool(getattr(sys, "frozen", False))


def data_dir():
    """Where backups and downloads live: the Games folder when frozen, the repo otherwise."""
    return HOME_DIR if frozen() else HERE.parent


def backups_dir():
    return data_dir() / "backups"


def default_prefix():
    return HOME_DIR / "prefix"


def game_folder(prefix):
    return Path(prefix).expanduser() / "drive_c" / "HeavyGear"


def child_environment(extra=None):
    """Environment for a script. A PyInstaller bundle points LD_LIBRARY_PATH at its own libraries,
    which would break the system's Wine and gamescope, so put the user's value back."""
    env = dict(os.environ)
    if frozen():
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    env.update({key: str(value) for key, value in (extra or {}).items() if value is not None})
    return env


# --- running the scripts -------------------------------------------------------------------

def start_script(name, args=(), env=None):
    """Start linux/NAME in its own process group with output merged into one pipe."""
    script = SCRIPTS / name
    if not script.is_file():
        raise FileNotFoundError(f"The script {name} was not found at {script}.")
    return subprocess.Popen(
        ["bash", str(script), *map(str, args)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        env=child_environment(env),
        start_new_session=True,
    )


def run_script(name, args=(), env=None, on_line=None, on_start=None):
    """Run a script to completion, passing each output line to on_line; returns all the output.
    Raises RuntimeError (with the end of the output) on a non-zero exit."""
    process = start_script(name, args, env)
    if on_start:
        on_start(process)
    lines = []
    with process.stdout:
        for line in process.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if on_line:
                on_line(line)
    code = process.wait()
    if code:
        tail = "\n".join(lines[-8:])
        if code < 0:
            raise RuntimeError(f"{name} was stopped.")
        raise RuntimeError(f"{name} failed (exit code {code}).\n{tail}")
    return "\n".join(lines)


def stop(process):
    """Interrupt a running script the way Ctrl+C would: it stops Wine and cleans up."""
    if process is not None and process.poll() is None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
        except (ProcessLookupError, PermissionError):
            pass


def hg_running():
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if (entry / "comm").read_text().strip().casefold().startswith("hg.exe"):
                    return True
            except OSError:
                continue
    return False


# --- dependencies ----------------------------------------------------------------------------

def package_hint(topic):
    try:
        result = subprocess.run(
            ["bash", "-c", f'. "{SCRIPTS / "distro.sh"}"; pkg_hint {topic}'],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return f"install '{topic}' with your distribution's package manager"
    return result.stdout.strip() or f"install '{topic}' with your distribution's package manager"


def check_dependencies(need_codec=True, need_glide_build=False, need_renderer_build=False):
    """[(label, found, required, hint)] for the programs the scripts use."""
    wanted = [
        ("Wine", ("wine",), True, "wine"),
        ("zstd (prefix backups)", ("zstd",), True, "zstd"),
        ("unshield (Indeo codec)", ("unshield",), False, "unshield") if need_codec else None,
        ("gamescope (full screen)", ("gamescope",), False, "gamescope"),
        ("clang, lld, llvm (build 3Dfx proxy)", ("clang", "lld-link", "llvm-dlltool"), True, "glidebuild")
        if need_glide_build else None,
        ("clang, lld, llvm (build Direct3D 9 renderer)", ("clang", "lld-link", "llvm-dlltool"), True, "glidebuild")
        if need_renderer_build else None,
    ]
    return [
        (label, all(shutil.which(command) for command in commands), required, package_hint(topic))
        for label, commands, required, topic in filter(None, wanted)
    ]


# --- prebuilt DLLs --------------------------------------------------------------------------

def _bundled(name):
    """A prebuilt DLL shipped inside the app (or in dist/); from a checkout the scripts build fresh ones."""
    for candidate in (ROOT / name, HERE.parent / "dist" / name):
        if candidate.is_file() and candidate.stat().st_size:
            return candidate
    return None


def renderer_dll():
    return _bundled("3dfx_hgd3d9.dll")


def glide_proxy():
    return _bundled("glide2x.dll")


def build_renderer(on_line=None):
    """Build the Direct3D 9 renderer from source (needs clang/lld and the Wine headers)."""
    script = ROOT / "renderer" / "hgd3d9" / "build.sh"
    if not script.is_file():
        raise FileNotFoundError("The Direct3D 9 renderer is not bundled and its source is not available.")
    process = subprocess.Popen(
        ["sh", str(script)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        errors="replace", env=child_environment(),
    )
    lines = []
    for line in process.stdout:
        lines.append(line.rstrip("\n"))
        if on_line:
            on_line(lines[-1])
    if process.wait():
        raise RuntimeError("Building the Direct3D 9 renderer failed.\n" + "\n".join(lines[-8:]))
    return script.parent / "hgd3d9.dll"


# --- settings -> script environment --------------------------------------------------------------

def launch_environment(settings):
    """Environment variables run-heavygear.sh reads, from the Launcher's choices."""
    env = {"HG_PREFIX": settings["prefix"]}
    if settings.get("disc2"):
        env["HG_DISC2"] = settings["disc2"]
    if settings.get("virtual_desktop"):
        env["HG_DESKTOP"] = settings["virtual_desktop"]
        env["HG_GAMESCOPE"] = "0"
    elif settings.get("gamescope", True):
        env["HG_SCALE"] = settings.get("scale", "integer")
        env["HG_FILTER"] = settings.get("filter", "nearest")
        if settings.get("gamescope_resolution"):
            env["HG_RES"] = settings["gamescope_resolution"]
    else:
        env["HG_GAMESCOPE"] = "0"
    return env


def install_desktop_entry(command):
    """An applications-menu entry for the app; returns its path. Replaces the old Launcher's entry."""
    folder = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "heavygear-launcher.desktop").unlink(missing_ok=True)
    entry = folder / "heavygear.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Heavy Gear\n"
        "Comment=Install, fix and play Heavy Gear (Wine)\n"
        f"Exec={command}\nTerminal=false\nCategories=Game;\n",
        encoding="utf-8",
    )
    return entry


def require_tk():
    """Import tkinter or exit with the install command for this distribution."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Tk is not installed, so the window cannot open. Install it with:\n  "
            + package_hint("tk")
        )
