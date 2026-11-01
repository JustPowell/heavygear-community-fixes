import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend_linux
from backend_linux import LinuxBackend

hg_linux = backend_linux.hg_linux
setup_core = backend_linux.setup_core


class Temp(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.prefix = self.root / "prefix"
        self.backend = LinuxBackend()
        patcher = mock.patch.object(hg_linux, "check_dependencies", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_game(self):
        game = hg_linux.game_folder(self.prefix)
        game.mkdir(parents=True)
        for name in ("HG.EXE", "HGSHELL.DLL", "HGSIM.DLL"):
            (game / name).write_bytes(b"x")
        return game

    def make_disc2(self):
        disc = self.root / "disc2"
        (disc / "VIDEO").mkdir(parents=True)
        (disc / "VIDEO" / "B51MOVIE.AVI").write_bytes(b"x")
        return disc

    def choices(self, **changes):
        choices = {
            "location": str(self.prefix), "disc1": "", "disc2": "", "controls": "action",
            "apply11": False, "patch11": "", "apply12": False, "patch12": "",
            "apply_fixes": True, "install_renderer": True, "renderer_touched": False,
            "install_glide": False, "glide_driver": "",
            "menu_fps": "30", "sim_fps": "30",
            "fixes": {fix.name: fix.default for fix in self.backend.fixes()},
            "renderer": "", "resolution": "",
            "gamescope": True, "scale": "integer", "filter": "nearest",
            "gamescope_resolution": "", "virtual_desktop": "",
        }
        choices.update(changes)
        return choices


class InstallRuleTests(Temp):
    def test_empty_prefix_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Choose a Wine prefix folder."):
            self.backend.validate_install(self.choices(location="  "))

    def test_a_new_install_checks_the_discs(self):
        with self.assertRaises(FileNotFoundError):
            self.backend.validate_install(self.choices(location=str(self.root / "nonexistent")))

    def test_renderer_left_at_its_default_is_dropped_without_12(self):
        self.make_game()
        with mock.patch.object(setup_core.hgfix, "game_version", return_value="1.0"):
            config = self.backend.validate_install(self.choices(controls="keep existing"))
            self.assertFalse(config["install_renderer"])
            with self.assertRaisesRegex(ValueError, "renderer requires the official 1.2"):
                self.backend.validate_install(self.choices(controls="keep existing", renderer_touched=True))
        with mock.patch.object(setup_core.hgfix, "game_version", return_value="1.2"):
            self.assertTrue(self.backend.validate_install(self.choices(controls="keep existing"))["install_renderer"])

    def test_missing_programs_refuse_the_run_and_are_listed(self):
        self.make_game()
        missing = [("Wine", False, True, "sudo pacman -S wine")]
        with mock.patch.object(hg_linux, "check_dependencies", return_value=missing), \
                mock.patch.object(setup_core.hgfix, "game_version", return_value="1.0"):
            with self.assertRaisesRegex(RuntimeError, "Install the missing programs first:\n\nWine: sudo pacman"):
                self.backend.validate_install(self.choices(controls="keep existing"))
            self.assertEqual(self.backend.missing_programs(self.choices()),
                             ["Missing: Wine. Install: sudo pacman -S wine"])

    def test_install_runs_setup_and_tracks_its_process(self):
        seen = []

        def run_setup(config, on_line, on_start):
            on_start("process")
            seen.append(self.backend.process)
            return Path("/game")

        with mock.patch.object(setup_core, "run_setup", side_effect=run_setup):
            note, game = self.backend.run_install({}, print)
        self.assertEqual((seen, game, self.backend.process), (["process"], Path("/game"), None))
        self.assertIn("disc 2", note)


class PlayTests(Temp):
    def test_find_game_on_a_fake_prefix(self):
        with mock.patch.object(hg_linux, "default_prefix", return_value=self.root / "default"):
            self.assertIsNone(self.backend.find_game({"prefix": str(self.prefix)}))
            self.assertEqual(self.backend.default_location({"prefix": str(self.prefix)}), str(self.prefix))
            self.make_game()
            self.assertEqual(self.backend.find_game({"prefix": str(self.prefix)}), str(self.prefix))
            self.assertEqual(self.backend.find_game({}), None)
        with mock.patch.object(hg_linux, "default_prefix", return_value=self.prefix):
            self.assertEqual(self.backend.find_game({}), str(self.prefix))
        info = self.backend.describe_game(str(self.prefix))
        self.assertEqual((info.found, info.game), (True, hg_linux.game_folder(self.prefix)))

    def test_launch_environment_from_the_choices(self):
        self.make_game()
        disc = self.make_disc2()
        with mock.patch.object(hg_linux, "hg_running", return_value=False):
            plan = self.backend.plan_apply(self.choices(disc2=str(disc), gamescope_resolution="1280x960"))
        env = hg_linux.launch_environment(plan["launch"])
        self.assertEqual(env, {"HG_PREFIX": str(self.prefix), "HG_DISC2": str(disc), "HG_SCALE": "integer",
                               "HG_FILTER": "nearest", "HG_RES": "1280x960"})
        plan = self.backend.plan_play(self.choices(gamescope=False, virtual_desktop="1024x768"))
        env = hg_linux.launch_environment(plan["launch"])
        self.assertEqual(env, {"HG_PREFIX": str(self.prefix), "HG_DESKTOP": "1024x768", "HG_GAMESCOPE": "0"})
        with self.assertRaisesRegex(ValueError, "WIDTHxHEIGHT"):
            self.backend.plan_play(self.choices(virtual_desktop="wide"))

    def test_borderless_with_a_blank_resolution_leaves_no_hgd3d9_res(self):
        game = self.make_game()
        (game / "PLUGIN").mkdir()
        (game / "PLUGIN" / "3dfx_hgd3d9.dll").write_bytes(b"x")
        (game / "hgd3d9.res").write_text("1280x960")
        fixes = {fix.name: fix.default for fix in self.backend.fixes()}
        fixes["borderless"] = True
        with mock.patch.object(hg_linux, "hg_running", return_value=False):
            plan = self.backend.plan_apply(self.choices(renderer="3dfx_hgd3d9.dll", fixes=fixes))
        self.assertTrue(plan["fixes"]["borderless"])
        with mock.patch.object(backend_linux.backend, "apply_fixes", return_value="applied") as apply_fixes:
            self.backend.apply(plan, lambda _line: None)
        self.assertIn("borderless", backend_linux.backend.fix_lists(apply_fixes.call_args.args[1]["fixes"])[0])
        self.assertFalse((game / "hgd3d9.res").exists())

    def test_a_stale_disc_2_folder_is_not_used(self):
        self.make_game()
        plan = self.backend.plan_play(self.choices(disc2=str(self.root / "gone")))
        self.assertNotIn("HG_DISC2", hg_linux.launch_environment(plan["launch"]))
        self.assertEqual(self.backend.check_path("disc2", str(self.root / "gone"))[0], False)

    def test_apply_refuses_while_the_game_runs(self):
        self.make_game()
        with mock.patch.object(hg_linux, "hg_running", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Exit Heavy Gear"):
                self.backend.plan_apply(self.choices())

    @unittest.skipIf(os.name == "nt", "runs a bash script in its own process group")
    def test_stop_signals_the_started_game(self):
        self.make_game()
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "run-heavygear.sh").write_text(
            "trap 'echo stopped; exit 130' INT\necho started\nwhile true; do sleep 0.1; done\n")
        lines, errors = [], []

        def play():
            try:
                self.backend.play(self.backend.plan_play(self.choices()), lines.append)
            except RuntimeError as exc:
                errors.append(str(exc))

        with mock.patch.object(hg_linux, "SCRIPTS", scripts):
            thread = threading.Thread(target=play)
            thread.start()
            for _ in range(100):
                if "started" in lines:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(self.backend.process)
            self.backend.stop()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertIn("stopped", lines)
        self.assertIn("Heavy Gear was stopped.", lines)
        self.assertEqual(errors, [])
        self.assertIsNone(self.backend.process)

    def test_menu_entry_starts_this_app(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"XDG_DATA_HOME": temp}):
            old = Path(temp) / "applications" / "heavygear-launcher.desktop"
            old.parent.mkdir()
            old.write_text("[Desktop Entry]\n")
            entry = self.backend.add_menu_entry()
            text = entry.read_text()
            self.assertFalse(old.exists())
        self.assertIn("Name=Heavy Gear\n", text)
        self.assertIn(f"Exec={sys.executable} {backend_linux.backend.HERE / 'heavygear.py'}\n", text)

    def test_settings_keep_the_old_keys(self):
        saved = self.backend.settings_to_save(self.choices(gamescope=False, disc2="/d2"))
        self.assertEqual((saved["prefix"], saved["gamescope"], saved["disc2"]), (str(self.prefix), "0", "/d2"))
        self.assertEqual(saved["game_path"], str(hg_linux.game_folder(self.prefix)))


if __name__ == "__main__":
    unittest.main()
