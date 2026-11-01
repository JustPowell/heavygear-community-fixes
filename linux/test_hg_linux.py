import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hg_linux
import installer_core
import setup_core
from hg_gui_common import list_renderers, read_selected_renderer


def make_script(folder, name, body):
    path = Path(folder) / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    return path


class RunScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(hg_linux, "SCRIPTS", Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_streams_lines_and_returns_output(self):
        make_script(self.temp.name, "ok.sh", 'echo one; echo two >&2; echo "arg=$1 env=$HG_X"\n')
        seen = []
        out = hg_linux.run_script("ok.sh", ["a"], {"HG_X": "y"}, seen.append)
        self.assertEqual(seen, ["one", "two", "arg=a env=y"])
        self.assertEqual(out.splitlines(), seen)

    def test_non_zero_exit_raises_with_the_tail(self):
        make_script(self.temp.name, "bad.sh", "echo boom; exit 3\n")
        with self.assertRaises(RuntimeError) as caught:
            hg_linux.run_script("bad.sh")
        self.assertIn("exit code 3", str(caught.exception))
        self.assertIn("boom", str(caught.exception))

    def test_missing_script_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            hg_linux.run_script("nope.sh")

    def test_stop_interrupts_a_running_script(self):
        make_script(self.temp.name, "slow.sh", "trap 'echo stopped; exit 130' INT\necho started\nwhile true; do sleep 0.1; done\n")
        holder = []
        lines = []

        def go():
            try:
                hg_linux.run_script("slow.sh", on_line=lines.append, on_start=holder.append)
            except RuntimeError as exc:
                lines.append("error:" + str(exc))

        import threading
        thread = threading.Thread(target=go)
        thread.start()
        for _ in range(100):
            if "started" in lines:
                break
            time.sleep(0.05)
        hg_linux.stop(holder[0])
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertIn("stopped", lines)


class EnvironmentTests(unittest.TestCase):
    def test_frozen_restores_the_users_library_path(self):
        with mock.patch.object(hg_linux, "frozen", return_value=True), mock.patch.dict(
            os.environ, {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/usr/lib"}
        ):
            self.assertEqual(hg_linux.child_environment()["LD_LIBRARY_PATH"], "/usr/lib")
        with mock.patch.object(hg_linux, "frozen", return_value=True), mock.patch.dict(
            os.environ, {"LD_LIBRARY_PATH": "/bundle"}
        ):
            os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
            self.assertNotIn("LD_LIBRARY_PATH", hg_linux.child_environment())

    def test_extra_values_are_strings_and_none_is_dropped(self):
        env = hg_linux.child_environment({"HG_A": Path("/x"), "HG_B": None})
        self.assertEqual(env["HG_A"], "/x")
        self.assertNotIn("HG_B", env)

    def test_launch_environment_with_gamescope(self):
        env = hg_linux.launch_environment(
            {"prefix": "/p", "disc2": "/d2", "gamescope": True, "scale": "fit",
             "filter": "linear", "gamescope_resolution": "1920x1440"}
        )
        self.assertEqual(env, {"HG_PREFIX": "/p", "HG_DISC2": "/d2", "HG_SCALE": "fit",
                               "HG_FILTER": "linear", "HG_RES": "1920x1440"})

    def test_launch_environment_without_gamescope_or_with_a_virtual_desktop(self):
        self.assertEqual(
            hg_linux.launch_environment({"prefix": "/p", "gamescope": False}),
            {"HG_PREFIX": "/p", "HG_GAMESCOPE": "0"})
        env = hg_linux.launch_environment({"prefix": "/p", "virtual_desktop": "1024x768", "gamescope": True})
        self.assertEqual(env["HG_DESKTOP"], "1024x768")
        self.assertEqual(env["HG_GAMESCOPE"], "0")

    def test_desktop_entry(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"XDG_DATA_HOME": temp}):
            entry = hg_linux.install_desktop_entry("python3 /x/launcher.py")
            self.assertIn("Exec=python3 /x/launcher.py", entry.read_text())
            self.assertEqual(entry.parent, Path(temp) / "applications")

    def test_package_hint_names_the_package(self):
        self.assertIn("tk", hg_linux.package_hint("tk"))

    def test_case_insensitive_renderer_helpers(self):
        with tempfile.TemporaryDirectory() as temp:
            game = Path(temp)
            (game / "plugin").mkdir()
            (game / "plugin" / "b.dll").write_bytes(b"x")
            (game / "plugin" / "A.DLL").write_bytes(b"x")
            (game / "plugin" / "note.txt").write_bytes(b"x")
            (game / "dllfile.ini").write_bytes(b'"b.dll"\r\n')
            self.assertEqual(list_renderers(game), ["A.DLL", "b.dll"])
            self.assertEqual(read_selected_renderer(game), "b.dll")
            self.assertEqual(list_renderers(game / "missing"), [])
            self.assertEqual(read_selected_renderer(game / "missing"), "")


class SetupCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.disc1 = self.root / "disc1"
        data = self.disc1 / "INSTALL" / "DATA"
        for name in installer_core.GAME_FILES:
            (data / name).parent.mkdir(parents=True, exist_ok=True)
            (data / name).write_bytes(b"x")
        self.disc2 = self.root / "disc2"
        (self.disc2 / "video").mkdir(parents=True)
        (self.disc2 / "video" / "b51movie.avi").write_bytes(b"x")
        self.prefix = self.root / "prefix"
        self.p11 = self.root / "hgp187d.exe"
        self.p12 = self.root / "HGPATC12.EXE"
        self.p11.write_bytes(b"x")
        self.p12.write_bytes(b"x")

    def config(self, **changes):
        base = {
            "prefix": str(self.prefix), "disc1": str(self.disc1), "disc2": str(self.disc2),
            "controls": "action", "patches": {}, "apply_fixes": True, "install_renderer": False,
            "install_glide": False, "glide_driver": "", "menu_fps": 30.0, "sim_fps": 30.0,
            "fixes": ["limiter"], "skipped": ["display"],
        }
        base.update(changes)
        return base

    def install_game(self, version="1.0"):
        game = hg_linux.game_folder(self.prefix)
        game.mkdir(parents=True)
        for name in installer_core.GAME_FILES:
            (game / name).write_bytes(b"x")
        return game

    def test_new_install_validates_the_discs_case_insensitively(self):
        config = setup_core.validate(self.config())
        self.assertFalse(config["existing"])
        self.assertEqual(config["disc2"], str(self.disc2.resolve()))

    def test_new_install_needs_both_discs(self):
        with self.assertRaises(FileNotFoundError):
            setup_core.validate(self.config(disc1=""))
        with self.assertRaises(FileNotFoundError):
            setup_core.validate(self.config(disc2=str(self.root)))

    def test_existing_install_needs_no_discs_and_limits_controls(self):
        self.install_game()
        with mock.patch.object(setup_core.hgfix, "game_version", return_value="1.0"):
            config = setup_core.validate(self.config(disc1="", disc2="", controls="keep existing"))
            self.assertTrue(config["existing"])
            with self.assertRaises(ValueError):
                setup_core.validate(self.config(disc1="", disc2="", controls="sim"))

    def test_patch_validation(self):
        with self.assertRaises(FileNotFoundError):
            setup_core.validate(self.config(patches={"1.1": str(self.root / "missing.exe")}))
        wrong = self.root / "other.exe"
        wrong.write_bytes(b"x")
        with self.assertRaises(ValueError):
            setup_core.validate(self.config(patches={"1.1": str(wrong)}))
        with self.assertRaises(ValueError):   # 1.2 follows 1.1
            setup_core.validate(self.config(patches={"1.2": str(self.p12)}))
        with self.assertRaises(ValueError):   # fixes don't support bare 1.1
            setup_core.validate(self.config(patches={"1.1": str(self.p11)}))
        config = setup_core.validate(
            self.config(patches={"1.1": str(self.p11), "1.2": str(self.p12)}))
        self.assertEqual([number for number, _ in config["patches"]], ["1.1", "1.2"])

    def test_already_12_skips_the_patches(self):
        self.install_game()
        with mock.patch.object(setup_core.hgfix, "game_version", return_value="1.2"):
            config = setup_core.validate(self.config(
                controls="keep existing", patches={"1.1": str(self.root / "gone.exe")}))
        self.assertEqual(config["patches"], [])

    def test_renderer_needs_12(self):
        with self.assertRaises(ValueError):
            setup_core.validate(self.config(install_renderer=True))
        config = setup_core.validate(self.config(
            install_renderer=True, patches={"1.1": str(self.p11), "1.2": str(self.p12)}))
        self.assertTrue(config["install_renderer"])

    def run_with_mocks(self, config):
        calls = []
        core = setup_core

        def script(name, args=(), env=None, on_line=None, on_start=None):
            calls.append(("script", name, list(map(str, args)), dict(env or {})))
            return ""

        game = hg_linux.game_folder(self.prefix)
        fake = {
            "run_script": script,
            "hg_running": lambda: False,
            "renderer_dll": lambda: Path("/r.dll"),
            "glide_proxy": lambda: Path("/g.dll"),
            "backups_dir": lambda: self.root / "backups",
        }
        with mock.patch.multiple(hg_linux, **fake), \
                mock.patch.object(core, "find_game_folder", return_value=game), \
                mock.patch.object(core.installer_core, "apply_controls",
                                  side_effect=lambda *a: calls.append(("controls", a[1])) or ""), \
                mock.patch.object(core.installer_core, "_run_tool",
                                  side_effect=lambda f, a: calls.append(("restore", a[1])) or ""), \
                mock.patch.object(core.installer_core, "install_renderer",
                                  side_effect=lambda *a: calls.append(("renderer",)) or "r"), \
                mock.patch.object(core.installer_core, "select_default_renderer",
                                  side_effect=lambda *a: calls.append(("select",)) or "s"), \
                mock.patch.object(core.installer_core, "require_official_12"), \
                mock.patch.object(core.installer_core, "apply_fixes",
                                  side_effect=lambda *a, **k: calls.append(("fixes", k["platform"])) or ""), \
                mock.patch.object(core.hgfix, "game_version", return_value="1.2"):
            core.run_setup(config, lambda line: None)
        return calls

    def test_step_order_for_a_full_new_install(self):
        config = setup_core.validate(self.config(
            controls="wasd", install_renderer=True, install_glide=True,
            patches={"1.1": str(self.p11), "1.2": str(self.p12)}))
        steps = [call[:2] if call[0] == "script" else call[:1] for call in self.run_with_mocks(config)]
        self.assertEqual(steps, [
            ("script", "setup-heavygear-wine.sh"), ("controls",), ("restore",),
            ("script", "backup.sh"), ("script", "apply-patches.sh"),
            ("renderer",), ("select",), ("fixes",), ("script", "setup-glide.sh")])

    def test_patch_environment_and_arguments(self):
        config = setup_core.validate(self.config(
            patches={"1.1": str(self.p11), "1.2": str(self.p12)}))
        calls = self.run_with_mocks(config)
        apply_call = next(call for call in calls if call[1:2] == ("apply-patches.sh",))
        self.assertEqual(apply_call[2], ["all"])
        self.assertEqual(apply_call[3]["HG_PATCH11"], str(self.p11.resolve()))
        self.assertEqual(apply_call[3]["HG_PATCH12"], str(self.p12.resolve()))
        self.assertEqual(apply_call[3]["HG_PREFIX"], str(self.prefix))
        self.assertTrue(any(call == ("fixes", "wine") for call in calls))

    def test_existing_backup_is_not_repeated(self):
        backups = self.root / "backups"
        backups.mkdir()
        (backups / "HeavyGear-1.0-prefix-20250101-000000.tar.zst").write_bytes(b"x")
        config = setup_core.validate(self.config(
            patches={"1.1": str(self.p11), "1.2": str(self.p12)}))
        names = [call[1] for call in self.run_with_mocks(config) if call[0] == "script"]
        self.assertNotIn("backup.sh", names)

    def test_refuses_while_the_game_runs(self):
        config = setup_core.validate(self.config())
        with mock.patch.object(hg_linux, "hg_running", return_value=True):
            with self.assertRaises(RuntimeError):
                setup_core.run_setup(config, lambda line: None)


class RunHeavyGearTests(unittest.TestCase):
    """run-heavygear.sh itself, with stand-ins for gamescope, wine, wineserver and findmnt on PATH."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.prefix = root / "prefix"
        (self.prefix / "drive_c" / "HeavyGear").mkdir(parents=True)
        (self.prefix / "drive_c" / "HeavyGear" / "HG.EXE").write_bytes(b"")
        (self.prefix / "dosdevices").mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        self.args = root / "gamescope-args"
        stubs = {
            "gamescope": f'printf "%s\\n" "$@" > "{self.args}"; echo "nodefault=${{NoDefaultCurrentDirectoryInExePath:-unset}}" >> "{self.args}"\n',
            "wine": f'echo "$*" >> "{root / "wine-calls"}"; echo "${{NGLIDE_RESOLUTION:-}}/${{NGLIDE_ASPECT:-}}" > "{root / "nglide"}"; '
                    'echo wine-stub\n',
            "wineserver": "true\n",
            "findmnt": "true\n",              # no disc in a drive, whatever the test machine has mounted
            "pgrep": "exit 1\n",              # no HG.EXE: the plain-Wine path's wait loop ends at once
            "sleep": "true\n",
        }
        for name, body in stubs.items():
            make_script(self.bin, name, body).chmod(0o755)

    def run_script(self, **env):
        import subprocess
        full = {k: v for k, v in os.environ.items()                            # the developer's own settings
                if not k.startswith(("HG_", "NGLIDE_"))}
        full.update(PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", HG_PREFIX=str(self.prefix),
                    HG_DISC2=self.temp.name, HG_WATCH="0", NoDefaultCurrentDirectoryInExePath="1", **env)
        script = Path(__file__).resolve().parent / "run-heavygear.sh"
        return subprocess.run(["bash", str(script)], env=full, capture_output=True, text=True, timeout=30)

    def gamescope_args(self):
        return self.args.read_text().splitlines()

    def test_full_screen_by_default(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.gamescope_args()
        self.assertIn("-f", args)
        self.assertNotIn("-W", args)

    def test_window_size_replaces_full_screen(self):
        result = self.run_script(HG_WINDOW="1280x960")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.gamescope_args()
        self.assertNotIn("-f", args)
        self.assertEqual(args[args.index("-W"):args.index("-W") + 4], ["-W", "1280", "-H", "960"])
        self.assertEqual(args[args.index("-w"):args.index("-w") + 4], ["-w", "640", "-h", "480"])

    def test_bad_window_size_is_refused(self):
        for bad in ("big", "0x0", "1280x"):
            with self.subTest(bad=bad):
                result = self.run_script(HG_WINDOW=bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("HG_WINDOW", result.stderr)
                self.assertFalse(self.args.exists())

    def test_window_size_without_gamescope_is_reported(self):
        result = self.run_script(HG_WINDOW="1280x960", HG_GAMESCOPE="0")
        self.assertIn("HG_WINDOW only applies inside gamescope", result.stdout)
        self.assertFalse(self.args.exists())

    def test_window_size_without_virtual_desktop(self):
        result = self.run_script(HG_WINDOW="1280x960", HG_VDESKTOP="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.gamescope_args()
        self.assertIn("-W", args)
        self.assertNotIn("explorer", args)

    def wine_calls(self):
        path = Path(self.temp.name) / "wine-calls"
        return path.read_text().splitlines() if path.exists() else []

    def test_hgd3d9_res_sets_game_size_and_emulated_modes(self):
        (self.prefix / "drive_c" / "HeavyGear" / "hgd3d9.res").write_text("1440x1080\r\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.gamescope_args()
        self.assertEqual(args[args.index("-w"):args.index("-w") + 4], ["-w", "1440", "-h", "1080"])
        self.assertEqual(args[args.index("-S") + 1], "fit")
        self.assertNotIn("explorer", args)                                  # no Wine virtual desktop
        self.assertTrue(any("reg add" in c and "EmulateModeset" in c and "AppDefaults\\HG.EXE" in c
                            for c in self.wine_calls()))

    def test_without_hgd3d9_res_the_640x480_desktop_is_kept(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.gamescope_args()
        self.assertEqual(args[args.index("-w"):args.index("-w") + 4], ["-w", "640", "-h", "480"])
        self.assertIn("/desktop=HeavyGear,640x480", args)
        self.assertTrue(any("reg delete" in c and "EmulateModeset" in c for c in self.wine_calls()))

    def test_unreadable_hgd3d9_res_is_ignored(self):
        for bad in ("big\n", "100x100\n", "9000x4000\n"):          # the renderer accepts 320-7680 x 240-4320
            with self.subTest(bad=bad):
                (self.prefix / "drive_c" / "HeavyGear" / "hgd3d9.res").write_text(bad)
                self.run_script()
                self.assertIn("/desktop=HeavyGear,640x480", self.gamescope_args())

    def test_hg_res_overrides_hgd3d9_res(self):
        (self.prefix / "drive_c" / "HeavyGear" / "hgd3d9.res").write_text("1440x1080")
        self.run_script(HG_RES="800x600")
        args = self.gamescope_args()
        self.assertEqual(args[args.index("-w"):args.index("-w") + 4], ["-w", "800", "-h", "600"])
        self.assertIn("/desktop=HeavyGear,800x600", args)

    def test_borderless_shell_runs_wine_directly(self):
        game = self.prefix / "drive_c" / "HeavyGear"
        (game / "HGSHELL.DLL").write_bytes(b"MZ\0.text\0\0\0.hgbdr\0\0")    # the section the borderless fix adds
        (game / "hgd3d9.res").write_text("1440x1080")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.args.exists())                                # no gamescope
        calls = self.wine_calls()
        self.assertIn("HG.EXE", calls)                                      # no virtual desktop
        self.assertTrue(any("reg delete" in c and "EmulateModeset" in c for c in calls))
        self.assertFalse(any("reg add" in c and "EmulateModeset" in c for c in calls))
        self.assertTrue(any("reg delete" in c and "AppDefaults\\HG.EXE " in c and "Version" in c for c in calls))
        self.run_script(HG_DESKTOP="1920x1440")
        self.assertIn("explorer /desktop=HeavyGear,1920x1440 HG.EXE", self.wine_calls())

    def test_borderless_with_dx5draw_turns_on_emulated_modes_and_3dfx_sets_nglide(self):
        game = self.prefix / "drive_c" / "HeavyGear"
        (game / "HGSHELL.DLL").write_bytes(b"MZ\0.hgbdr\0")
        nglide = Path(self.temp.name) / "nglide"
        driver = game / "glide2x_real.dll"
        for renderer, glide, emulated, settings in (("DX5DRAW.DLL", "", True, "/"),
                                                    ("3dfxgear.dll", "nGlide NGLIDE_RESOLUTION", False, "1/1"),
                                                    ("3dfxgear.dll", "dgVoodoo", True, "/"),
                                                    ("3dfx_hgd3d9.dll", "nGlide NGLIDE_RESOLUTION", False, "/")):
            with self.subTest(renderer=renderer, glide=glide):
                driver.write_text(glide)
                (game / "DLLFILE.INI").write_text(renderer + "\r\n")
                (Path(self.temp.name) / "wine-calls").unlink(missing_ok=True)
                result = self.run_script()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.args.exists())
                calls = self.wine_calls()
                self.assertEqual(emulated, any("reg add" in c and "EmulateModeset" in c for c in calls))
                self.assertEqual(not emulated, any("reg delete" in c and "EmulateModeset" in c for c in calls))
                self.assertEqual(settings, nglide.read_text().strip())
        driver.write_text("NGLIDE_RESOLUTION")
        (game / "DLLFILE.INI").write_text("3dfxgear.dll")
        self.run_script(NGLIDE_RESOLUTION="2")                             # the player's own choice wins
        self.assertEqual("2/1", nglide.read_text().strip())

    def test_wine_can_find_the_game_in_its_folder(self):
        self.run_script()
        self.assertIn("nodefault=unset", self.gamescope_args())


class SetupScriptTests(unittest.TestCase):
    """setup-heavygear-wine.sh over an already installed (patched) game, with stand-ins for wine on PATH."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.disc1, self.disc2, self.prefix = root / "disc1", root / "disc2", root / "prefix"
        data = self.disc1 / "INSTALL" / "DATA"
        for rel, content in {"HG.EXE": "v1.0 exe", "ANET2.DLL": "v1.0 anet", "ANET/WIPX2.DLL": "v1.0 ipx",
                             "PLUGIN/DX5DRAW.DLL": "v1.0 plugin", "NEW.DAT": "only on the disc",
                             "ACTION/INPUTW.MAP": "action map", "ACTION/ACTION.CCT": "cct"}.items():
            (data / rel).parent.mkdir(parents=True, exist_ok=True)
            (data / rel).write_text(content)
        (self.disc1 / "HELP").mkdir()
        (self.disc1 / "HELP" / "MANUAL.HLP").write_text("help")
        (self.disc2 / "VIDEO").mkdir(parents=True)
        (self.disc2 / "VIDEO" / "B51MOVIE.AVI").write_bytes(b"")
        self.game = self.prefix / "drive_c" / "HeavyGear"
        for rel, content in {"HG.EXE": "patched exe", "anet2.dll": "v1.2 anet", "anet/wipx2.dll": "v1.2 ipx",
                             "PLUGIN/dx5draw.dll": "v1.2 plugin"}.items():
            (self.game / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.game / rel).write_text(content)
        (self.prefix / "dosdevices").mkdir()
        self.codec = root / "ir50_32.dll"
        self.codec.write_bytes(b"codec")
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in {"wine": "echo wine-stub\n", "wineserver": "true\n",
                           "wineboot": 'mkdir -p "$WINEPREFIX/drive_c/windows/system32"; touch "$WINEPREFIX/system.reg"\n'}.items():
            make_script(self.bin, name, body).chmod(0o755)

    def run_setup(self, *extra):
        import subprocess
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        script = Path(__file__).resolve().parent / "setup-heavygear-wine.sh"
        return subprocess.run(["bash", str(script), "--prefix", str(self.prefix), "--disc1", str(self.disc1),
                               "--disc2", str(self.disc2), "--codec", str(self.codec), *extra],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_unknown_control_scheme_is_an_error(self):
        result = self.run_setup("--controls", "akshun")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AKSHUN", result.stderr)

    def test_disc_files_in_other_case_are_not_added_next_to_patched_ones(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        names = sorted(str(p.relative_to(self.game)) for p in self.game.rglob("*") if p.is_file())
        lowered = [n.lower() for n in names]
        self.assertEqual(len(lowered), len(set(lowered)), names)            # no name twice in another case
        self.assertEqual((self.game / "anet2.dll").read_text(), "v1.2 anet")
        self.assertEqual((self.game / "anet" / "wipx2.dll").read_text(), "v1.2 ipx")
        self.assertFalse((self.game / "ANET").exists())                      # the existing folder was reused
        self.assertEqual((self.game / "PLUGIN" / "dx5draw.dll").read_text(), "v1.2 plugin")
        self.assertEqual((self.game / "HG.EXE").read_text(), "patched exe")
        self.assertEqual((self.game / "NEW.DAT").read_text(), "only on the disc")
        self.assertEqual((self.game / "INPUTW.MAP").read_text(), "action map")
        self.assertTrue((self.game / "HELP" / "MANUAL.HLP").exists())


class HgfixCodeTests(unittest.TestCase):
    """Hand-assembled patch code in patcher/hgfix.py (hg_linux puts the patcher on sys.path)."""

    def test_coopfix_skip_jump_lands_on_the_final_jmp(self):
        import hgfix
        for ver in ("1.0", "1.2"):
            with self.subTest(ver=ver):
                code = hgfix.build_coopfix(0x10300000, hgfix.PROFILES[ver]["coopfix"])
                jnz = code.index(b"\x75")                           # first jnz after "test eax,eax"
                self.assertEqual(code[jnz - 2:jnz], b"\x85\xc0")
                self.assertEqual(jnz + 2 + code[jnz + 1], len(code) - 5)
                self.assertEqual(code[-5], 0xe9)
                self.assertEqual(code.count(b"\x52") >= 1 and code.count(b"\x5a") >= 2, True)   # edx saved and restored

    def test_moviebg_is_a_wine_default_with_both_versions(self):
        import hgfix
        self.assertIn("moviebg", hgfix.choose_fixes("wine", [], []))
        self.assertNotIn("moviebg", hgfix.choose_fixes("windows", [], []))
        for ver in ("1.0", "1.2"):
            m = hgfix.PROFILES[ver]["moviebg"]
            self.assertEqual((m["orig"][:2], m["new"]), (b"\x6a\x01", b"\x6a\x00"))



if __name__ == "__main__":
    unittest.main()
