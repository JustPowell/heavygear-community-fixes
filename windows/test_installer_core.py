import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import installer_core
import win_system


def setUpModule():
    # The real check looks for a running HG.EXE: the tests must not depend on whether the developer is playing.
    patcher = mock.patch.object(installer_core, "ensure_game_not_running")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class InstallerCoreTests(unittest.TestCase):
    def make_disc(self, root):
        data = root / "INSTALL" / "DATA"
        for name in installer_core.GAME_FILES:
            path = data / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode("ascii"))
        action = data / "ACTION"
        action.mkdir()
        (action / "INPUTW.MAP").write_bytes(b"action controls")
        (action / "GAMEKEY.MAP").write_bytes(b"game keys")
        return root

    def test_install_from_disc_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disc = self.make_disc(root / "disc")
            game = root / "game"
            game.mkdir()
            (game / "HG.EXE").write_bytes(b"user's existing file")

            result = installer_core.install_game(disc, game, controls="action")

            self.assertEqual(result, game.resolve())
            self.assertEqual((game / "HG.EXE").read_bytes(), b"user's existing file")
            self.assertEqual((game / "HGSIM.DLL").read_bytes(), b"HGSIM.DLL")
            self.assertEqual((game / "INPUTW.MAP").read_bytes(), b"action controls")

    def test_the_multi_language_disc_uses_its_english_controls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disc = self.make_disc(root / "disc")
            data = disc / "INSTALL" / "DATA"
            (data / "ACTION").rename(data / "ACTIONE")              # sets per language, no plain ACTION
            (data / "ACTIONF").mkdir()
            (data / "ACTIONF" / "INPUTW.MAP").write_bytes(b"french")
            game = root / "game"
            with mock.patch.object(installer_core, "apply_controls"):
                installer_core.install_game(disc, game, controls="wasd")
            self.assertEqual((game / "INPUTW.MAP").read_bytes(), b"action controls")
            with self.assertRaisesRegex(FileNotFoundError, "missing the sim control files"):
                installer_core.install_game(disc, root / "other", controls="sim")

    def test_find_disc1_accepts_disc_folder_with_expected_nesting(self):
        with tempfile.TemporaryDirectory() as temporary:
            disc = self.make_disc(Path(temporary) / "HG-DISC-1")
            self.assertEqual(installer_core.find_disc1(disc.parent), disc.resolve())

    def test_install_rejects_destination_inside_disc_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            disc = self.make_disc(Path(temporary) / "disc")
            with self.assertRaisesRegex(ValueError, "outside the disc 1 source"):
                installer_core.install_game(disc, disc / "INSTALL" / "DATA" / "copy")

    def test_existing_install_validation_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            (game / "HG.EXE").touch()
            with self.assertRaisesRegex(FileNotFoundError, "HGSHELL.DLL, HGSIM.DLL"):
                installer_core.find_game_folder(game)

    def test_wasd_control_install_preserves_original_maps(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            lines = [f"line {index}".encode("ascii") for index in range(250)]
            (game / "INPUTW.MAP").write_bytes(b"\r\n".join(lines) + b"\r\n")
            (game / "GAMEKEY.MAP").write_bytes(
                b"TOGGLE_AUTOPILOT a\r\nCOCKPIT_VIEW c\r\n"
            )
            installer_core.apply_controls(game, "wasd")
            self.assertTrue((game / "INPUTW.MAP.orig").is_file())
            self.assertTrue((game / "GAMEKEY.MAP.orig").is_file())
            self.assertIn(b"TOGGLE_AUTOPILOT o", (game / "GAMEKEY.MAP").read_bytes())
            self.assertIn(b"COCKPIT_VIEW v", (game / "GAMEKEY.MAP").read_bytes())

    def test_fix_application_calls_bundled_patcher_with_windows_options(self):
        with mock.patch.object(installer_core.hgfix, "main") as patcher:
            installer_core.apply_fixes("C:/Games/HG", 30.0, "60", ["anet2"], ["display"])
        patcher.assert_called_once_with(
            [
                "C:/Games/HG",
                "--platform",
                "windows",
                "--menu-fps",
                "30",
                "--sim-fps",
                "60",
                "--fix",
                "anet2",
                "--skip",
                "display",
            ]
        )

    def test_font_family_reads_true_type_name_table(self):
        name = "Gear Test".encode("utf-16-be")
        name_table = (
            struct.pack(">HHH", 0, 1, 18)
            + struct.pack(">HHHHHH", 3, 1, 0x0409, 1, len(name), 0)
            + name
        )
        font = bytearray(28 + len(name_table))
        struct.pack_into(">H", font, 4, 1)
        font[12:16] = b"name"
        struct.pack_into(">II", font, 20, 28, len(name_table))
        font[28:] = name_table
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.ttf"
            path.write_bytes(font)
            self.assertEqual(win_system.font_family(path), "Gear Test")

    def test_renderer_install_copies_only_valid_x86_dll(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            for name in installer_core.GAME_FILES:
                (game / name).write_bytes(b"game")
            plugin = game / "PLUGIN"
            plugin.mkdir()
            renderer = bytearray(96)
            renderer[:2] = b"MZ"
            struct.pack_into("<I", renderer, 0x3C, 64)
            renderer[64:68] = b"PE\0\0"
            struct.pack_into("<H", renderer, 68, 0x014C)
            struct.pack_into("<H", renderer, 64 + 22, 0x2000)
            renderer_path = root / installer_core.RENDERER_NAME
            renderer_path.write_bytes(renderer)
            with mock.patch.object(installer_core, "bundled_path", return_value=renderer_path):
                installer_core.install_renderer(game)
            self.assertEqual(
                (plugin / installer_core.RENDERER_NAME).read_bytes(),
                renderer_path.read_bytes(),
            )

    def test_renderer_install_sets_aside_the_old_name_and_keeps_its_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            for name in installer_core.GAME_FILES:
                (game / name).write_bytes(b"game")
            plugin = game / "PLUGIN"
            plugin.mkdir()
            (plugin / "3dfx_hgrender.dll").write_bytes(b"old")
            (game / "hgrender.res").write_bytes(b"1280x960\r\n")
            renderer_path = root / installer_core.RENDERER_NAME
            renderer_path.write_bytes(b"new")
            with mock.patch.object(installer_core, "bundled_path", return_value=renderer_path), \
                    mock.patch.object(installer_core, "validate_x86_dll"):
                installer_core.install_renderer(game)
            self.assertEqual(sorted(p.name for p in plugin.iterdir()), [installer_core.RENDERER_NAME])
            self.assertEqual(len(list((game / "hgd3d9-runs").glob("3dfx_hgrender.dll.*.bak"))), 1)
            self.assertEqual((game / "hgd3d9.res").read_bytes(), b"1280x960\r\n")
            self.assertFalse((game / "hgrender.res").exists())

    def glide_game(self, root):
        game = root / "game"
        game.mkdir()
        for name in installer_core.GAME_FILES:
            (game / name).write_bytes(b"game")
        driver = root / "nGlide" / "glide2x.dll"
        driver.parent.mkdir()
        driver.write_bytes(b"nglide")
        no_proxy = mock.patch.object(installer_core, "bundled_path", return_value=root / "none" / "glide2x.dll")
        no_proxy.start()                                   # a checkout without a built proxy, unless a test says so
        self.addCleanup(no_proxy.stop)
        return game, driver

    def test_the_bundled_proxy_goes_in_front_of_the_driver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game, driver = self.glide_game(root)
            proxy = root / "dist" / "glide2x.dll"
            proxy.parent.mkdir()
            proxy.write_bytes(b"proxy")
            (game / "glide2x.dll").write_bytes(b"nglide")      # nGlide copied in earlier, no proxy yet
            with mock.patch.object(installer_core, "validate_x86_dll"):
                note = installer_core.install_glide_driver(game, game / "glide2x.dll", proxy)  # that very copy
                self.assertIn("particle-fix proxy as glide2x.dll", note)
                self.assertIn("up to date", installer_core.install_glide_driver(game, driver, proxy))
            self.assertEqual((game / "glide2x.dll").read_bytes(), b"proxy")
            self.assertEqual((game / "glide2x_real.dll").read_bytes(), b"nglide")
            self.assertEqual([p.read_bytes() for p in game.glob("glide2x.dll.*.bak")], [b"nglide"])
            with mock.patch.object(installer_core, "bundled_path", return_value=proxy), \
                    mock.patch.object(installer_core, "validate_x86_dll"):
                proxy.write_bytes(b"newer proxy")                 # an app update carries a newer one
                installer_core.install_glide_driver(game, driver)
            self.assertEqual((game / "glide2x.dll").read_bytes(), b"newer proxy")

    def test_glide_driver_is_copied_under_both_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            game, driver = self.glide_game(Path(temporary))
            with mock.patch.object(installer_core, "validate_x86_dll"):
                installer_core.install_glide_driver(game, driver)
                self.assertIn("up to date", installer_core.install_glide_driver(game, driver))
            self.assertEqual((game / "glide2x.dll").read_bytes(), b"nglide")
            self.assertEqual((game / "glide2x_real.dll").read_bytes(), b"nglide")

    def test_glide_driver_keeps_the_particle_fix_proxy(self):
        with tempfile.TemporaryDirectory() as temporary:
            game, driver = self.glide_game(Path(temporary))
            (game / "glide2x.dll").write_bytes(b"proxy")
            (game / "glide2x_real.dll").write_bytes(b"old driver")
            with mock.patch.object(installer_core, "validate_x86_dll"):
                self.assertIn("proxy is kept", installer_core.install_glide_driver(game, driver))
            self.assertEqual((game / "glide2x.dll").read_bytes(), b"proxy")
            self.assertEqual((game / "glide2x_real.dll").read_bytes(), b"nglide")
            self.assertEqual([p.read_bytes() for p in game.glob("glide2x_real.dll.*.bak")], [b"old driver"])
            with mock.patch.object(installer_core, "validate_x86_dll"), \
                    self.assertRaisesRegex(ValueError, "particle-fix proxy"):
                installer_core.install_glide_driver(game, game / "glide2x.dll")

    def test_glide_driver_backs_up_a_wrapper_it_replaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            game, driver = self.glide_game(Path(temporary))
            (game / "glide2x.dll").write_bytes(b"dgvoodoo")
            with mock.patch.object(installer_core, "validate_x86_dll"):
                installer_core.install_glide_driver(game, driver)
            self.assertEqual((game / "glide2x.dll").read_bytes(), b"nglide")
            self.assertEqual([p.read_bytes() for p in game.glob("glide2x.dll.*.bak")], [b"dgvoodoo"])

    def test_the_proxy_is_refused_as_the_driver(self):
        with tempfile.TemporaryDirectory() as temporary:
            game, driver = self.glide_game(Path(temporary))
            driver.write_bytes(b"MZ ... glidelog attached ...")       # a proxy build, browsed to by mistake
            with mock.patch.object(installer_core, "validate_x86_dll"), \
                    self.assertRaisesRegex(ValueError, "is the particle-fix proxy, not a Glide driver"):
                installer_core.install_glide_driver(game, driver)
            self.assertFalse((game / "glide2x_real.dll").exists())

    def test_glide_driver_must_be_a_32_bit_glide2x_dll(self):
        with tempfile.TemporaryDirectory() as temporary:
            game, driver = self.glide_game(Path(temporary))
            with self.assertRaisesRegex(ValueError, "not a valid"):
                installer_core.install_glide_driver(game, driver)
            other = driver.with_name("glide3x.dll")
            other.write_bytes(b"x")
            with self.assertRaisesRegex(FileNotFoundError, "glide2x.dll"):
                installer_core.install_glide_driver(game, other)
            self.assertFalse((game / "glide2x.dll").exists())

    def graphics_game(self, root, plugins, value=1):
        game = root / "game"
        (game / "PLUGIN").mkdir(parents=True)
        for name in plugins:
            (game / "PLUGIN" / name).write_bytes(b"plugin")
        settings = bytearray(108)
        settings[0x48:0x53] = b"vesa480.dll"
        settings[0x58:0x5c] = value.to_bytes(4, "little", signed=True)
        (game / "hgsnd.cfg").write_bytes(settings)
        return game

    def graphics_type(self, game):
        return int.from_bytes((game / "hgsnd.cfg").read_bytes()[0x58:0x5c], "little", signed=True)

    def test_graphics_type_follows_the_games_own_list(self):
        # As seen in the game: 3Dfx 0, Direct3D 9 renderer 1, Software 640 -1 (with these five plugins)
        plugins = ("3dfx_hgd3d9.dll", "3dfxgear.dll", "dx5draw.dll.off", "i76draw.dll", "renddraw.dll")
        with tempfile.TemporaryDirectory() as temporary:
            game = self.graphics_game(Path(temporary), plugins)
            (game / "glide2x.dll").write_bytes(b"driver")
            self.assertEqual(installer_core.listed_renderers(game), ["3dfxgear.dll", "3dfx_hgd3d9.dll"])
            self.assertIn("Graphics Type", installer_core.select_graphics_type(game, "3dfxgear.dll"))
            self.assertEqual(self.graphics_type(game), 0)
            installer_core.select_graphics_type(game, "i76draw.dll")
            self.assertEqual(self.graphics_type(game), -1)
            installer_core.select_graphics_type(game, "3dfx_hgd3d9.dll")
            self.assertEqual(self.graphics_type(game), 1)
            self.assertIsNone(installer_core.select_graphics_type(game, "3dfx_hgd3d9.dll"))   # already set
            self.assertEqual((game / "hgsnd.cfg").read_bytes()[0x48:0x53], b"vesa480.dll")    # the rest kept
            self.assertTrue((game / "hgsnd.cfg.hglauncher.bak").is_file())

    def test_graphics_type_without_a_glide_driver_or_saved_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = self.graphics_game(Path(temporary), ("3dfx_hgd3d9.dll", "3dfxgear.dll", "DX5DRAW.DLL"))
            with mock.patch.object(installer_core, "find_glide_driver", return_value=None):
                self.assertEqual(installer_core.listed_renderers(game), ["3dfx_hgd3d9.dll", "DX5DRAW.DLL"])
                installer_core.select_graphics_type(game, "dx5draw.dll")
                self.assertEqual(self.graphics_type(game), 1)
                self.assertIn("not in the game's", installer_core.select_graphics_type(game, "3dfxgear.dll"))
                self.assertEqual(self.graphics_type(game), 1)
            (game / "hgsnd.cfg").unlink()
            self.assertIsNone(installer_core.select_graphics_type(game, "dx5draw.dll"))
            self.assertFalse((game / "hgsnd.cfg").exists())

    def test_invalid_renderer_machine_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            game.mkdir()
            for name in installer_core.GAME_FILES:
                (game / name).write_bytes(b"game")
            plugin = game / "PLUGIN"
            plugin.mkdir()
            renderer = bytearray(96)
            renderer[:2] = b"MZ"
            struct.pack_into("<I", renderer, 0x3C, 64)
            renderer[64:68] = b"PE\0\0"
            struct.pack_into("<H", renderer, 68, 0x8664)
            struct.pack_into("<H", renderer, 86, 0x2000)
            renderer_path = root / installer_core.RENDERER_NAME
            renderer_path.write_bytes(renderer)
            with mock.patch.object(installer_core, "bundled_path", return_value=renderer_path):
                with self.assertRaisesRegex(ValueError, "32-bit"):
                    installer_core.install_renderer(game)


    def test_find_disc1_rejects_an_empty_source(self):
        with self.assertRaisesRegex(FileNotFoundError, "Select the disc 1"):
            installer_core.find_disc1("  ")

    def test_patcher_exit_codes_are_reported_readably(self):
        def stops_with(code):
            def main(_args):
                raise SystemExit(code)
            return main

        with self.assertRaisesRegex(RuntimeError, "exit code 3"):
            installer_core._run_tool(stops_with(3), [])
        with self.assertRaisesRegex(RuntimeError, "no such file"):
            installer_core._run_tool(stops_with("no such file"), [])
        self.assertEqual(installer_core._run_tool(stops_with(0), []), "")

    def test_game_version_is_none_for_unknown_or_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(installer_core.hgfix.game_version(temporary))
            (Path(temporary) / "HGSIM.DLL").write_bytes(b"not a pe file")
            self.assertIsNone(installer_core.hgfix.game_version(temporary))

    def test_unknown_operation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown elevated operation"):
            installer_core.run_privileged_operation({"operation": "format-disk"})

    def test_settings_operation_only_writes_renderer_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            for name in installer_core.GAME_FILES:
                (game / name).write_bytes(b"game")
            config = {"operation": "settings", "game": str(game),
                      "settings": {"DLLFILE.INI": "3dfx_hgd3d9.dll"}}
            installer_core.run_privileged_operation(config)
            self.assertEqual((game / "DLLFILE.INI").read_bytes(), b"3dfx_hgd3d9.dll\r\n")
            config["settings"] = {"HG.EXE": "evil"}
            with self.assertRaisesRegex(ValueError, "Unsupported renderer setting"):
                installer_core.run_privileged_operation(config)
            self.assertEqual((game / "HG.EXE").read_bytes(), b"game")

    def test_renderer_requires_official_12(self):
        with mock.patch.object(installer_core.hgfix, "game_version", return_value="1.0"):
            with self.assertRaisesRegex(ValueError, "requires the official 1.2"):
                installer_core.require_official_12("C:/Games/HG")
        with mock.patch.object(installer_core.hgfix, "game_version", return_value="1.2"):
            installer_core.require_official_12("C:/Games/HG")


class OfficialPatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.disc = InstallerCoreTests().make_disc(root / "disc")
        self.game = root / "game"
        self.game.mkdir()
        for name in installer_core.GAME_FILES:
            (self.game / name).write_bytes(name.encode("ascii"))
        self.patch12 = root / "HGPATC12.EXE"
        self.patch12.write_bytes(b"patcher")
        self.patch11 = root / "hgp187d.exe"
        self.patch11.write_bytes(b"patcher")

    def test_patch_must_have_the_official_name(self):
        wrong = self.patch12.with_name("setup.exe")
        wrong.write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "must be named 'hgpatc12.exe'"):
            installer_core.validate_patch("1.2", wrong, self.game)
        self.assertEqual(
            installer_core.validate_patch("1.2", self.patch12, self.game), self.patch12.resolve()
        )

    def test_patch_changed_after_selection_is_refused(self):
        digest = installer_core.sha256_file(self.patch12)
        self.patch12.write_bytes(b"swapped")
        with self.assertRaisesRegex(ValueError, "changed after it was selected"):
            installer_core.validate_patch("1.2", self.patch12, self.game, expected_sha256=digest)

    def test_official_11_requires_a_clean_disc_copy(self):
        installer_core.validate_patch("1.1", self.patch11, self.game, self.disc)
        (self.game / "HGSIM.DLL").write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "HGSIM.DLL is not the clean disc"):
            installer_core.validate_patch("1.1", self.patch11, self.game, self.disc)
        with self.assertRaisesRegex(ValueError, "disc 1 source is required"):
            installer_core.validate_patch("1.1", self.patch11, self.game, None)

    def run_patcher(self, returncode, new_contents):
        def fake_run(command, **_kwargs):
            if new_contents is not None:
                (self.game / "HGSIM.DLL").write_bytes(new_contents)
            return subprocess.CompletedProcess(command, returncode)

        with mock.patch.object(installer_core.subprocess, "run", side_effect=fake_run):
            return installer_core._run_patcher(self.game, self.patch12.resolve(), "1.2")

    def test_patcher_that_changes_nothing_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "did not change the game files"):
            self.run_patcher(0, None)

    def test_patcher_failure_after_changes_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "exited with code 5"):
            self.run_patcher(5, b"half patched")

    def test_12_patcher_exit_code_is_ignored_when_every_file_is_12(self):
        # The 1.2 patcher has been seen to report 1 after a complete patch.
        with mock.patch.object(installer_core, "is_complete_12", return_value=True):
            self.assertIn("all three files are now the 1.2 build", self.run_patcher(1, b"patched"))
        with mock.patch.object(installer_core, "is_complete_12", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "exited with code 1"):
                self.run_patcher(1, b"half patched")

    def test_complete_12_needs_every_file_changed_and_both_dlls_at_12(self):
        every = list(installer_core.GAME_FILES)
        self.assertFalse(installer_core.is_complete_12(self.game, every))        # not PE images
        with mock.patch.object(installer_core.hgfix, "PEFile"), \
                mock.patch.object(installer_core.hgfix, "detect", return_value=("1.2", None)):
            self.assertTrue(installer_core.is_complete_12(self.game, every))
            self.assertFalse(installer_core.is_complete_12(self.game, ["HGSHELL.DLL", "HGSIM.DLL"]))  # HG.EXE left
        with mock.patch.object(installer_core.hgfix, "PEFile"), \
                mock.patch.object(installer_core.hgfix, "detect", side_effect=[("1.2", None), (None, None)]):
            self.assertFalse(installer_core.is_complete_12(self.game, every))       # HGSIM.DLL not 1.2

    def test_patched_game_must_identify_as_12(self):
        with mock.patch.object(installer_core.hgfix, "game_version", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not a 1.2 build"):
                self.run_patcher(0, b"something else")
        with mock.patch.object(installer_core.hgfix, "game_version", return_value="1.2"):
            self.assertIn("HGSIM.DLL", self.run_patcher(0, b"patched"))

    def test_already_12_skips_official_updates_without_touching_the_machine(self):
        config = {"patches": [("1.1", str(self.patch11)), ("1.2", str(self.patch12))],
                  "disc1": str(self.disc)}
        with mock.patch.object(installer_core.hgfix, "game_version", return_value="1.2"), \
                mock.patch.object(installer_core, "register_official_patch_paths") as register:
            output = installer_core._run_official_patches(self.game, config)
        register.assert_not_called()
        self.assertIn("already at official 1.2", output[0])

    def test_validation_failure_happens_before_backup_or_registry_changes(self):
        (self.game / "HGSIM.DLL").write_bytes(b"modified")
        config = {"patches": [("1.1", str(self.patch11))], "disc1": str(self.disc)}
        with mock.patch.object(installer_core.hgfix, "game_version", return_value=None), \
                mock.patch.object(installer_core, "register_official_patch_paths") as register, \
                mock.patch.object(installer_core, "backup_game_files") as backup:
            with self.assertRaises(ValueError):
                installer_core._run_official_patches(self.game, config)
        register.assert_not_called()
        backup.assert_not_called()


class DefaultRendererTests(unittest.TestCase):
    """Installing the Direct3D 9 renderer also selects it, unless the game already selects another one."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.game = Path(self.temporary.name)
        self.setting = self.game / "DLLFILE.INI"

    def selected(self):
        return self.setting.read_bytes().decode("ascii").strip()

    def test_selected_when_nothing_is_selected(self):
        message = installer_core.select_default_renderer(self.game)
        self.assertIn("Selected Direct3D 9 renderer", message)
        self.assertEqual(self.selected(), installer_core.RENDERER_NAME)

    def test_selected_in_place_of_the_direct3d_plugin_the_fix_removes(self):
        self.setting.write_bytes(b'"DX5DRAW.DLL"\r\n')
        installer_core.select_default_renderer(self.game)
        self.assertEqual(self.selected(), installer_core.RENDERER_NAME)
        self.assertTrue((self.game / "DLLFILE.INI.hglauncher.bak").is_file())

    def test_selected_in_place_of_the_renderer_under_its_old_name(self):
        self.setting.write_bytes(b"3dfx_hgrender.dll\r\n")
        installer_core.select_default_renderer(self.game)
        self.assertEqual(self.selected(), installer_core.RENDERER_NAME)

    def test_an_explicit_other_choice_is_kept(self):
        self.setting.write_bytes(b"3dfxgear.dll\r\n")
        message = installer_core.select_default_renderer(self.game)
        self.assertIn("Left the selected renderer (3dfxgear.dll)", message)
        self.assertEqual(self.selected(), "3dfxgear.dll")

    def test_install_steps_put_the_renderer_before_the_fixes(self):
        calls = []
        config = {"install_renderer": True, "apply_fixes": True, "menu_fps": 30, "sim_fps": 30,
                  "fixes": [], "skipped": []}
        with mock.patch.object(installer_core, "require_official_12"), \
                mock.patch.object(installer_core, "install_renderer",
                                  side_effect=lambda g: calls.append("install") or "i"), \
                mock.patch.object(installer_core, "select_default_renderer",
                                  side_effect=lambda g: calls.append("select") or "s"), \
                mock.patch.object(installer_core, "apply_fixes",
                                  side_effect=lambda *a: calls.append("fixes") or "f"):
            output = installer_core._project_steps(self.game, config)
        self.assertEqual(calls, ["install", "select", "fixes"])
        self.assertEqual(output, ["i", "s", "f"])


class D3dPluginAsideTests(unittest.TestCase):
    """The 'dx5draw' fix: PLUGIN\\DX5DRAW.DLL is renamed to DX5DRAW.DLL.off and back."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.game = Path(self.temporary.name)
        (self.game / "PLUGIN").mkdir()
        self.plugin = self.game / "PLUGIN" / "DX5DRAW.DLL"
        self.parked = self.game / "PLUGIN" / "DX5DRAW.DLL.off"
        self.plugin.write_bytes(b"plugin")
        self.aside = installer_core.hgfix.set_d3d_plugin_aside

    def test_fix_is_on_by_default_on_windows_only(self):
        fixes = installer_core.hgfix
        self.assertEqual(fixes.FIXES["dx5draw"][0], ("windows",))
        self.assertIn("dx5draw", fixes.choose_fixes("windows", [], []))
        self.assertNotIn("dx5draw", fixes.choose_fixes("windows", [], ["dx5draw"]))
        self.assertNotIn("dx5draw", fixes.choose_fixes("wine", [], []))
        self.assertIn("dx5draw", fixes.choose_fixes("wine", ["dx5draw"], []))

    def test_sets_the_plugin_aside_and_puts_it_back(self):
        self.assertIn("set aside", self.aside(str(self.game), True))
        self.assertFalse(self.plugin.exists())
        self.assertEqual(self.parked.read_bytes(), b"plugin")
        self.assertEqual(self.aside(str(self.game), True), "DX5DRAW.DLL: already set aside")
        self.assertEqual(self.aside(str(self.game), False), "DX5DRAW.DLL: put back")
        self.assertEqual(self.plugin.read_bytes(), b"plugin")
        self.assertFalse(self.parked.exists())
        self.assertIsNone(self.aside(str(self.game), False))

    def test_file_names_are_matched_without_regard_to_case(self):
        self.plugin.rename(self.game / "PLUGIN" / "dx5draw.dll")
        self.assertIn("set aside", self.aside(str(self.game), True))
        self.assertEqual(self.aside(str(self.game), False), "DX5DRAW.DLL: put back")
        self.assertTrue((self.game / "PLUGIN" / "dx5draw.dll").is_file())

    def test_leaves_the_plugin_when_it_is_the_selected_renderer(self):
        (self.game / "DLLFILE.INI").write_bytes(b'"dx5draw.dll"\r\n')
        message = self.aside(str(self.game), True)
        self.assertIn("NOT set aside", message)
        self.assertTrue(self.plugin.is_file())

    def test_other_selected_renderers_do_not_block_it(self):
        (self.game / "DLLFILE.INI").write_bytes(b"3dfx_hgd3d9.dll\r\n")
        self.assertIn("set aside", self.aside(str(self.game), True))

    def test_does_not_overwrite_an_existing_parked_file(self):
        self.parked.write_bytes(b"older")
        self.assertIn("NOT set aside", self.aside(str(self.game), True))
        self.assertEqual(self.plugin.read_bytes(), b"plugin")
        self.assertEqual(self.parked.read_bytes(), b"older")

    def test_nothing_to_do_without_the_plugin(self):
        self.plugin.unlink()
        self.assertIsNone(self.aside(str(self.game), True))
        self.assertIsNone(self.aside(str(self.game), False))


if __name__ == "__main__":
    unittest.main()
