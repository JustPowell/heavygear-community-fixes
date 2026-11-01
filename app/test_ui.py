import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_linux
import backend_windows

try:
    import tkinter as tk

    ROOT = tk.Tk()
    ROOT.withdraw()
    import ui
except Exception:  # no tkinter or no display (headless CI)
    ROOT = None


@unittest.skipIf(ROOT is None, "needs tkinter and a display")
class WindowTests(unittest.TestCase):
    """Builds the window over each back end in a scratch home: no game, settings in a temp folder."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        for patcher in (
            mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / "config"),
                                         "LOCALAPPDATA": str(self.home / "config"),
                                         # the Windows default game folder is ~/Games/HeavyGear
                                         "USERPROFILE": str(self.home), "HOME": str(self.home)}),
            mock.patch.object(backend_linux.hg_linux, "default_prefix", return_value=self.home / "prefix"),
            mock.patch.object(backend_linux.hg_linux, "check_dependencies", return_value=[]),
            mock.patch.object(backend_windows, "get_game_path_from_registry", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.destroy()

    def app(self, backend, saved=None):
        window = tk.Toplevel(ROOT)
        window.withdraw()
        self.windows.append(window)
        return ui.App(window, backend, saved)

    def settings(self, **values):
        path = self.home / "config" / "HeavyGearFixes" / "launcher.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(values))

    def make_game(self, folder):
        folder.mkdir(parents=True)
        for name in ("HG.EXE", "HGSHELL.DLL", "HGSIM.DLL"):
            (folder / name).write_bytes(b"x")
        (folder / "PLUGIN").mkdir()
        for name in ("3dfx_hgd3d9.dll", "DX5DRAW.DLL"):
            (folder / "PLUGIN" / name).write_bytes(b"plugin")
        (folder / "DLLFILE.INI").write_bytes(b"DX5DRAW.DLL\r\n")
        return folder

    def fake_job(self, app):
        """Start a job that runs until the returned event is set."""
        release = threading.Event()
        app.run_job("Working...", lambda report: release.wait(10))
        self.addCleanup(release.set)
        return release

    # --- 5.1: bottom strip and close guard ------------------------------------------------------------
    def test_progress_shows_only_while_busy(self):
        app = self.app(backend_linux.LinuxBackend())
        ROOT.update()
        self.assertFalse(app.progress.winfo_manager())
        release = self.fake_job(app)
        ROOT.update()
        self.assertTrue(app.progress.winfo_manager())
        release.set()
        for _ in range(50):
            ROOT.after(20)
            ROOT.update()
            if not app.busy:
                break
        self.assertFalse(app.busy)
        self.assertFalse(app.progress.winfo_manager())

    def test_closing_while_busy_asks_on_linux(self):
        backend = backend_linux.LinuxBackend()
        app = self.app(backend)
        self.fake_job(app)
        with mock.patch.object(ui.messagebox, "askyesno", return_value=False) as ask, \
                mock.patch.object(backend, "stop") as stop:
            app.close()
            ask.assert_called_once()
            stop.assert_not_called()
        self.assertTrue(app.root.winfo_exists())
        with mock.patch.object(ui.messagebox, "askyesno", return_value=True), \
                mock.patch.object(backend, "stop") as stop:
            app.close()
            stop.assert_called_once()
        self.assertTrue(app.close_when_done)

    def test_closing_while_busy_is_refused_on_windows(self):
        app = self.app(backend_windows.WindowsBackend())
        self.fake_job(app)
        with mock.patch.object(ui.messagebox, "showwarning") as warn:
            app.close()
        warn.assert_called_once()
        self.assertTrue(app.root.winfo_exists())

    # --- 5.2: Play page ---------------------------------------------------------------------------------
    def test_play_page_describes_the_game_folder(self):
        game = self.make_game(self.home / "game")
        self.settings(game_path=str(game))
        app = self.app(backend_windows.WindowsBackend())
        self.assertEqual(app.current_page(), "play")
        self.assertIn(str(game), app.header_status.get())
        self.assertIn("unknown version", app.header_status.get())
        direct3d = ui.RENDERER_LABELS["dx5draw.dll"]            # the in-game name, whatever the file's case
        self.assertIn(direct3d, app.header_status.get())
        self.assertEqual(list(app.renderer_combo.cget("values")), [ui.KEEP_RENDERER, ui.D3D9_LABEL, direct3d])
        self.assertEqual(app.renderer_label.get(), direct3d)
        self.assertEqual(str(app.resolution_entry.cget("state")), "disabled")
        self.assertFalse(hasattr(app, "stop_button"))

    def test_bad_resolution_is_refused_before_anything_runs(self):
        backend = backend_linux.LinuxBackend()
        self.make_game(self.home / "prefix" / "drive_c" / "HeavyGear")
        app = self.app(backend)
        self.assertEqual(app.current_page(), "play")
        self.assertTrue(hasattr(app, "stop_button"))
        app.renderer_label.set(ui.D3D9_LABEL)
        app.vars["resolution"].set("huge")
        with mock.patch.object(ui.messagebox, "showerror") as error, \
                mock.patch.object(backend, "apply") as apply:
            app.apply_and_play()
        self.assertIn("WIDTHxHEIGHT", error.call_args.args[1])
        apply.assert_not_called()
        self.assertFalse(app.busy)

    # --- 5.3: Fixes page --------------------------------------------------------------------------------
    def test_fix_boxes_follow_the_platform_and_saved_choices(self):
        self.settings(fixes={"limiter": False, "partdepth": True, "dx5draw": True})
        linux = self.app(backend_linux.LinuxBackend())
        self.assertEqual(list(linux.fix_checks), ["limiter", "display", "anet2", "moviebg", "partdepth", "borderless"])
        self.assertFalse(linux.fix_vars["limiter"].get())
        self.assertTrue(linux.fix_vars["partdepth"].get())
        self.assertTrue(linux.fix_vars["display"].get())        # not saved: the patcher's default
        self.assertFalse(linux.fix_vars["borderless"].get())    # no 1.2 game: the v1.2-only fixes default off
        windows = self.app(backend_windows.WindowsBackend())
        self.assertEqual(list(windows.fix_checks),
                         ["limiter", "dx5draw", "anet2", "movie32", "partdepth", "nodisc", "music", "borderless"])
        self.assertTrue(windows.fix_vars["dx5draw"].get())

    # --- 5.4: Install page ------------------------------------------------------------------------------
    def test_a_stale_remembered_path_is_marked_not_found(self):
        self.settings(disc2=str(self.home / "gone"))
        app = self.app(backend_linux.LinuxBackend())
        self.assertEqual(app.current_page(), "install")
        note, label = app.path_checks["disc2"]
        self.assertTrue(note.get().startswith("✗ Not found"))
        self.assertEqual(str(label.cget("style")), "Bad.TLabel")
        disc = self.home / "disc2"
        (disc / "VIDEO").mkdir(parents=True)
        (disc / "VIDEO" / "B51MOVIE.AVI").write_bytes(b"x")
        app.vars["disc2"].set(str(disc))
        self.assertTrue(note.get().startswith("✓"))

    def test_start_reports_validation_errors(self):
        app = self.app(backend_windows.WindowsBackend())
        app.vars["disc1"].set("")
        with mock.patch.object(ui.messagebox, "showerror") as error:
            app.start_install()
        self.assertIn("disc 1", error.call_args.args[1])
        self.assertFalse(app.busy)

    def test_controls_follow_the_location(self):
        app = self.app(backend_windows.WindowsBackend())
        self.assertEqual(app.vars["controls"].get(), "action")
        game = self.make_game(self.home / "game")
        app.vars["location"].set(str(game))
        app.refresh()
        self.assertEqual(app.vars["controls"].get(), "keep existing")
        self.assertEqual(list(app.controls_combo.cget("values")), list(ui.EXISTING_CONTROLS))

    def test_declining_the_11_update_undoes_the_set_up(self):
        backend = backend_windows.WindowsBackend()
        app = self.app(backend)
        config = {"patches": [("1.1", "hgp187d.exe", "0" * 64)], "mounted_images": ["C:\\HG-DISC-1.iso"]}
        with mock.patch.object(backend, "validate_install", return_value=config), \
                mock.patch.object(backend, "cancel_install") as cancel, \
                mock.patch.object(ui.messagebox, "askyesno", return_value=False):
            app.start_install()
        cancel.assert_called_once_with(config)
        self.assertFalse(app.busy)

    def test_install_page_says_when_indeo_is_already_installed(self):
        for installed in (False, True):
            with mock.patch.object(backend_windows.win_system, "indeo_installed", return_value=installed):
                app = self.app(backend_windows.WindowsBackend())
            self.assertEqual(hasattr(app, "indeo_tip"), installed)
            self.assertEqual(app.vars["install_media"].get(), not installed)

    # --- 5.5: Tools page --------------------------------------------------------------------------------
    def test_tools_page_only_on_linux(self):
        self.assertIn("tools", self.app(backend_linux.LinuxBackend()).pages)
        self.assertNotIn("tools", self.app(backend_windows.WindowsBackend()).pages)


if __name__ == "__main__":
    unittest.main()
