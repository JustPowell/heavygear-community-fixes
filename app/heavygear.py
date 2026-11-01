#!/usr/bin/env python3
"""Heavy Gear: install or update the game from your own discs, choose fixes and renderer, and play.

One app for Linux (Wine) and Windows; the platform parts are in backend_linux.py and backend_windows.py."""

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend  # noqa: E402  (puts windows/, linux/ and patcher/ on sys.path)
import hg_gui_common  # noqa: E402
import win_elevation  # noqa: E402


@contextlib.contextmanager
def replaced(*stubs):
    """Temporarily replace (object, attribute, value) triples."""
    saved = [(target, name, getattr(target, name)) for target, name, _value in stubs]
    for target, name, value in stubs:
        setattr(target, name, value)
    try:
        yield
    finally:
        for target, name, value in saved:
            setattr(target, name, value)


def self_test():
    """Build every page over both back ends, first with no game (Install page) and then with a fake one (Play
    page). Any error propagates, so the process exits non-zero with the traceback."""
    import backend_linux
    import backend_windows

    assert backend.validate_resolution("1920X1080") == "1920x1080"
    if backend.frozen() and os.name != "nt":     # the Linux build must carry the scripts its pages run
        for script in ("setup-heavygear-wine.sh", "run-heavygear.sh", "backup.sh", "restore.sh"):
            assert (backend_linux.hg_linux.SCRIPTS / script).is_file(), script
    try:
        import tkinter as tk

        root = tk.Tk()
    except Exception as exc:  # no Tk or no display (headless CI without xvfb)
        print(f"Self-test: skipped building the window ({exc}).")
        return
    import ui

    root.withdraw()
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        os.environ["XDG_CONFIG_HOME"] = os.environ["LOCALAPPDATA"] = str(home / "config")
        with replaced(
            (backend_linux.hg_linux, "default_prefix", lambda: home / "prefix"),
            (backend_windows, "get_game_path_from_registry", lambda: None),
        ):
            for make, game in (
                (backend_linux.LinuxBackend, home / "prefix" / "drive_c" / "HeavyGear"),
                (backend_windows.WindowsBackend, home / "game"),
            ):
                for has_game, page in ((False, "install"), (True, "play")):
                    if has_game:
                        game.mkdir(parents=True)
                        for name in ("HG.EXE", "HGSHELL.DLL", "HGSIM.DLL"):
                            (game / name).write_bytes(b"x")
                    window = tk.Toplevel(root)
                    window.withdraw()
                    app = ui.App(window, make(), {"game_path": str(game)} if has_game else {})
                    assert app.current_page() == page, (make.name, app.current_page())
                    assert set(app.pages) == {"play", "fixes", "install", *make.extra_pages}
                    window.destroy()
    root.destroy()
    print("Self-test passed.")


def main():
    hg_gui_common.ensure_standard_streams()
    parser = argparse.ArgumentParser(description="Heavy Gear")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(win_elevation.ELEVATED_FLAG, dest="elevated_op", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.elevated_op:
        raise SystemExit(win_elevation.elevated_entry(
            arguments.elevated_op, backend.installer_core.run_privileged_operation))
    if arguments.self_test:
        self_test()
        return
    if os.name != "nt":
        import hg_linux

        hg_linux.require_tk()
    hg_gui_common.enable_dpi_awareness()
    import tkinter as tk

    import ui

    root = tk.Tk()
    ui.App(root, backend.for_this_platform())
    root.mainloop()


if __name__ == "__main__":
    main()
