import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend
import backend_windows
from backend_windows import WindowsBackend

installer_core = backend_windows.installer_core


def make_game(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("HG.EXE", "HGSHELL.DLL", "HGSIM.DLL"):
        (folder / name).write_bytes(b"x")
    return folder


def make_disc1(folder):
    data = Path(folder) / "INSTALL" / "DATA"
    data.mkdir(parents=True)
    (data / "HG.EXE").write_bytes(b"x")
    return Path(folder)


def make_disc2(folder):
    disc = Path(folder)
    (disc / "VIDEO").mkdir(parents=True)
    (disc / "VIDEO" / "B51MOVIE.AVI").write_bytes(b"x")
    return disc


class Temp(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.backend = WindowsBackend()

    def choices(self, **changes):
        choices = {
            "location": str(self.root / "game"),
            "disc1": "",
            "controls": "action",
            "apply11": False, "patch11": "",
            "apply12": False, "patch12": "",
            "apply_fixes": True,
            "install_renderer": True, "renderer_touched": False,
            "install_media": False, "codec_path": "",
            "install_glide": False, "glide_driver": "",
            "disc2": "", "music_folder": "",
            "menu_fps": "30", "sim_fps": "30",
            "fixes": {fix.name: fix.default for fix in self.backend.fixes()},
            "renderer": "", "resolution": "",
        }
        choices.update(changes)
        return choices

    def patch_file(self, name):
        path = self.root / name
        path.write_bytes(b"patch")
        return str(path)


class InstallValidationTests(Temp):
    def test_empty_location_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Choose an install folder."):
            self.backend.validate_install(self.choices(location="  "))

    def test_new_install_needs_disc_1(self):
        with self.assertRaisesRegex(FileNotFoundError, "disc 1"):
            self.backend.validate_install(self.choices())

    def test_existing_install_is_detected_and_limits_controls(self):
        make_game(self.root / "game")
        with self.assertRaisesRegex(ValueError, "Keep existing or WASD"):
            self.backend.validate_install(self.choices())
        config = self.backend.validate_install(self.choices(controls="keep existing"))
        self.assertTrue(config["existing"])
        self.assertFalse(config["install_renderer"])      # default on, but this run doesn't reach 1.2

    def test_patches_in_order_on_a_new_install(self):
        disc = make_disc1(self.root / "disc1")
        with self.assertRaisesRegex(ValueError, "1.2 update follows 1.1"):
            self.backend.validate_install(self.choices(
                disc1=str(disc), apply12=True, patch12=self.patch_file("hgpatc12.exe")))

    def test_patch_file_must_exist_and_have_the_official_name(self):
        make_game(self.root / "game")
        with self.assertRaisesRegex(FileNotFoundError, "official 1.2 patch executable"):
            self.backend.validate_install(self.choices(controls="keep existing", apply12=True))
        with self.assertRaisesRegex(ValueError, "named 'hgpatc12.exe'"):
            self.backend.validate_install(self.choices(
                controls="keep existing", apply12=True, patch12=self.patch_file("patch.exe")))

    def test_valid_patches_carry_their_hash(self):
        make_game(self.root / "game")
        config = self.backend.validate_install(self.choices(
            controls="keep existing", apply12=True, patch12=self.patch_file("HGPATC12.EXE")))
        version, path, digest = config["patches"][0]
        self.assertEqual((version, len(digest)), ("1.2", 64))
        self.assertTrue(config["install_renderer"])

    def test_an_install_at_12_asks_for_no_patch_files(self):
        make_game(self.root / "game")
        with mock.patch.object(installer_core.hgfix, "game_version", return_value="1.2"):
            config = self.backend.validate_install(self.choices(controls="keep existing", apply11=True, apply12=True))
        self.assertEqual(config["patches"], [])
        self.assertTrue(config["install_renderer"])

    def test_11_without_12_and_fixes_is_refused(self):
        make_game(self.root / "game")
        disc = make_disc1(self.root / "disc1")
        with self.assertRaisesRegex(ValueError, "not the intermediate 1.1 update"):
            self.backend.validate_install(self.choices(
                controls="keep existing", disc1=str(disc), apply11=True, patch11=self.patch_file("hgp187d.exe"),
                install_renderer=False))

    def test_11_needs_disc_1(self):
        make_game(self.root / "game")
        with self.assertRaisesRegex(ValueError, "Select disc 1 to verify"):
            self.backend.validate_install(self.choices(
                controls="keep existing", apply11=True, patch11=self.patch_file("hgp187d.exe"), apply_fixes=False))

    def test_renderer_ticked_without_12_is_refused(self):
        make_game(self.root / "game")
        with self.assertRaisesRegex(ValueError, "renderer requires the official 1.2"):
            self.backend.validate_install(self.choices(controls="keep existing", renderer_touched=True))

    def test_cutscene_support_checks_the_codec_before_starting(self):
        make_game(self.root / "game")
        disc = make_disc1(self.root / "disc1")
        with mock.patch.object(backend_windows.win_system, "resolve_indeo_codec",
                               side_effect=FileNotFoundError("no codec")) as resolve:
            with self.assertRaisesRegex(FileNotFoundError, "no codec"):
                self.backend.validate_install(self.choices(
                    controls="keep existing", disc1=str(disc), install_media=True))
        self.assertEqual(resolve.call_args.args[:2], (None, str(disc)))

    def test_cutscene_support_is_on_until_windows_has_indeo(self):
        machine = (mock.patch.object(backend_windows, "find_adjacent_disc1", return_value=""),
                   mock.patch.object(backend_windows, "find_disc2", return_value=""),
                   mock.patch.object(backend_windows, "get_game_path_from_registry", return_value=None),
                   mock.patch.object(installer_core, "find_glide_driver", return_value=None))
        for patcher in machine:
            patcher.start()
            self.addCleanup(patcher.stop)
        saved = {"game_path": str(self.root / "game")}
        for installed in (False, True):
            with mock.patch.object(backend_windows.win_system, "indeo_installed", return_value=installed):
                self.assertEqual(self.backend.initial_choices(saved)["install_media"], not installed)

    def test_cutscene_support_without_disc_1_says_what_it_needs(self):
        make_game(self.root / "game")
        with self.assertRaisesRegex(ValueError, "Cutscene support .* needs disc 1"):
            self.backend.validate_install(self.choices(controls="keep existing", install_media=True))

    def test_disc_images_are_mounted_and_their_drives_used(self):
        disc = make_disc1(self.root / "mounted")
        image = self.root / "HG-DISC-1.iso"
        image.write_bytes(b"iso")
        with mock.patch.object(backend_windows.disc2_media, "mount_image", return_value=(str(disc), True)) as mount, \
                mock.patch.object(backend_windows.disc2_media, "dismount_image") as dismount:
            config = self.backend.validate_install(self.choices(disc1=str(image)))
            mount.assert_called_once_with(str(image))
            self.assertEqual((config["source"], config["mounted_images"]), (str(disc), [str(image)]))
            dismount.assert_not_called()                                   # still needed by the install
            with self.assertRaisesRegex(ValueError, "Keep existing or WASD"):   # a refused install lets it go
                make_game(self.root / "game")
                self.backend.validate_install(self.choices(disc1=str(image)))
            dismount.assert_called_once_with(str(image))

    def test_a_disc_2_image_is_never_ripped(self):
        game = make_game(self.root / "game")
        disc2 = make_disc2(self.root / "E")
        music = {"nodisc": True, "music": True}
        with mock.patch.object(backend_windows.disc2_media, "is_cd_drive", return_value=True):
            self.assertEqual(backend_windows.disc2_plan(game, music, True, str(disc2), "")[1], str(disc2))
            with self.assertRaisesRegex(ValueError, "holds no music tracks"):
                backend_windows.disc2_plan(game, music, True, str(disc2), "", image=True)
        image = self.root / "disc2.iso"                                    # not mounted yet: taken as disc 2
        self.assertEqual(backend_windows.disc2_plan(game, {"nodisc": True}, True, str(image), "")[0], str(image))
        self.assertEqual(self.backend.check_path("disc2", str(self.root / "none.iso"))[0], False)
        image.write_bytes(b"iso")
        self.assertEqual(self.backend.check_path("disc2", str(image)), (True, "Found"))

    def test_an_mds_disc_2_gives_the_cutscenes_and_the_music(self):
        game = make_game(self.root / "game")
        music = {"nodisc": True, "music": True}
        image = str(self.root / "HEAVYG2.mds")
        self.assertEqual(backend_windows.disc2_plan(game, music, True, image, ""), (image, image, None))
        disc2 = make_disc2(self.root / "E")                               # mounted: its drive, music from the .mdf
        self.assertEqual(backend_windows.disc2_plan(game, music, True, str(disc2), "", image)[1], image)

    def test_an_mds_image_is_mounted_as_a_temporary_iso_and_cleaned_up(self):
        written = []

        class FakeImage:
            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            def write_iso(self, destination):
                destination.write_bytes(b"iso")
                written.append(destination)
                return destination

        with mock.patch.object(backend_windows.disc_image, "MdsImage", FakeImage), \
                mock.patch.object(backend_windows.disc2_media, "mount_image", return_value=("E:\\", True)), \
                mock.patch.object(backend_windows.disc2_media, "dismount_image") as dismount:
            drive, iso = backend_windows.mount_disc_image(str(self.root / "Heavy Gear.mds"))
            self.assertEqual((drive, iso), ("E:\\", str(written[0])))
            self.assertTrue(written[0].is_file())
            backend_windows.dismount_images([iso])
            dismount.assert_called_once_with(iso)
        self.assertFalse(written[0].parent.exists())                      # the temporary folder is gone

    def test_music_is_ripped_from_an_mds_image_with_its_reader(self):
        game = make_game(self.root / "game")
        config = {"music_folder": None, "rip_drive": str(self.root / "HEAVYG2.mds")}
        with mock.patch.object(backend_windows.disc2_media, "rip_audio") as rip:
            backend_windows.prepare_music(config, game, lambda line: None)
        self.assertIs(rip.call_args.kwargs["opener"], backend_windows.disc_image.MdsImage)
        with mock.patch.object(backend_windows.disc2_media, "rip_audio") as rip:
            backend_windows.prepare_music({"music_folder": None, "rip_drive": "D:\\"}, game, lambda line: None)
        self.assertIs(rip.call_args.kwargs["opener"], backend_windows.disc2_media.CdromDrive)

    def test_glide_driver_is_checked_before_starting_and_passed_on(self):
        make_game(self.root / "game")
        with self.assertRaisesRegex(FileNotFoundError, "glide2x.dll"):
            self.backend.validate_install(self.choices(controls="keep existing", install_glide=True))
        wrong = self.root / "glide3x.dll"
        wrong.write_bytes(b"x")
        with self.assertRaisesRegex(FileNotFoundError, "glide2x.dll"):
            self.backend.validate_install(self.choices(controls="keep existing", install_glide=True,
                                                       glide_driver=str(wrong)))
        driver = self.root / "nglide" / "GLIDE2X.DLL"
        driver.parent.mkdir()
        driver.write_bytes(b"x")
        with mock.patch.object(installer_core, "validate_x86_dll") as validate:
            config = self.backend.validate_install(self.choices(controls="keep existing", install_glide=True,
                                                                glide_driver=str(driver)))
        validate.assert_called_once()
        self.assertEqual(config["glide_driver"], str(driver.resolve()))
        config = self.backend.validate_install(self.choices(controls="keep existing", glide_driver=str(driver)))
        self.assertIsNone(config["glide_driver"])      # not ticked: nothing is copied


class Disc2PlanTests(Temp):
    def make_game(self, videos=False, tracks=False):
        game = self.root / "game"
        game.mkdir()
        if videos:
            make_disc2(game)
        if tracks:
            (game / "MUSIC").mkdir()
            (game / "MUSIC" / "TRACK02.WAV").write_bytes(b"x")
        return game

    def plan(self, game, fixes, disc2="", folder="", community=True):
        return backend_windows.disc2_plan(game, fixes, community, str(disc2), str(folder))

    def test_nothing_is_planned_without_the_disc_free_options(self):
        self.assertEqual((None, None, None), self.plan(self.make_game(), ["limiter"]))

    def test_disc_free_options_need_the_project_fixes(self):
        with self.assertRaises(ValueError):
            self.plan(self.make_game(), ["nodisc"], community=False)

    def test_cutscenes_need_disc_2_unless_the_game_already_has_them(self):
        game = self.make_game()
        with self.assertRaises(ValueError):
            self.plan(game, ["nodisc"])
        with self.assertRaises(FileNotFoundError):                 # a folder that is not disc 2
            self.plan(game, ["nodisc"], disc2=self.root)
        disc = make_disc2(self.root / "disc2")
        self.assertEqual((str(disc), None, None), self.plan(game, ["nodisc"], disc2=disc))
        make_disc2(game)
        self.assertEqual((None, None, None), self.plan(game, ["nodisc"]))

    def test_music_comes_from_a_folder_a_drive_or_what_the_game_already_has(self):
        rips = self.root / "rips"
        rips.mkdir()
        game = self.make_game(videos=True)
        self.assertEqual((None, None, str(rips)), self.plan(game, ["music"], folder=rips))
        with self.assertRaises(FileNotFoundError):
            self.plan(game, ["music"], folder=rips / "missing")
        with self.assertRaises(ValueError):
            self.plan(game, ["music"])                       # no folder, no drive, no tracks yet
        with mock.patch.object(backend_windows.disc2_media, "is_cd_drive", return_value=True):
            disc = make_disc2(self.root / "disc2")
            self.assertEqual((str(disc), str(disc), None), self.plan(game, ["music"], disc2=disc))
        (game / "MUSIC").mkdir()
        (game / "MUSIC" / "Track03.mp3").write_bytes(b"x")
        self.assertEqual((None, None, None), self.plan(game, ["music"]))

    def test_an_audio_only_drive_can_be_ripped_when_the_game_has_its_cutscenes(self):
        game = self.make_game(videos=True)
        with mock.patch.object(backend_windows.disc2_media, "is_cd_drive", return_value=True), \
                mock.patch.object(backend_windows.disc2_media, "find_disc2", side_effect=FileNotFoundError):
            self.assertEqual((None, "E:\\", None), self.plan(game, ["music"], disc2="E:"))

    def test_the_finish_note_says_what_is_still_needed(self):
        self.assertIn("not needed", backend_windows.disc_note(["music", "nodisc"]))
        self.assertIn("music", backend_windows.disc_note(["nodisc"]))
        self.assertIn("Mount disc 2", backend_windows.disc_note([]))


class RunInstallTests(Temp):
    CONFIG = {
        "source": "D:\\", "game": "C:\\HG", "controls": "action", "existing": False, "patches": [],
        "apply_fixes": True, "install_renderer": False, "install_media": False, "codec_path": None,
        "glide_driver": None, "menu_fps": 30.0, "sim_fps": 30.0, "fixes": ["limiter"], "skipped": [], "disc2": None,
        "rip_drive": None, "music_folder": None,
    }

    def run_install(self, install_game=None, privileged=None, **changes):
        config = {**self.CONFIG, **changes}
        lines = []
        with mock.patch.object(installer_core, "install_game", side_effect=install_game,
                               return_value=Path("C:\\HG")) as install, \
                mock.patch.object(installer_core, "run_privileged_operation", side_effect=privileged,
                                  return_value="fixed") as local, \
                mock.patch.object(backend_windows, "run_elevated_config", return_value="elevated") as elevated:
            note, game = self.backend.run_install(config, lines.append)
        return install, local, elevated, lines, note

    def test_mounted_images_are_dismounted_when_the_install_ends(self):
        with mock.patch.object(backend_windows.disc2_media, "dismount_image") as dismount:
            self.run_install(mounted_images=["C:\\HG-DISC-1.iso"])
            dismount.assert_called_once_with("C:\\HG-DISC-1.iso")
            dismount.reset_mock()
            with self.assertRaises(RuntimeError):
                self.run_install(install_game=RuntimeError, mounted_images=["C:\\HG-DISC-1.iso"])
            dismount.assert_called_once_with("C:\\HG-DISC-1.iso")

    def test_plain_run_installs_then_applies_in_process(self):
        install, local, elevated, lines, note = self.run_install()
        install.assert_called_once_with("D:\\", "C:\\HG", "action", False)
        self.assertEqual(local.call_args.args[0]["operation"], "project")
        elevated.assert_not_called()
        self.assertIn("fixed", lines)
        self.assertIn("Mount disc 2", note)

    def test_permission_denied_elevates_each_step(self):
        install, local, elevated, lines, _ = self.run_install(
            install_game=PermissionError, privileged=PermissionError)
        operations = [call.args[0]["operation"] for call in elevated.call_args_list]
        self.assertEqual(operations, ["install", "project"])
        self.assertTrue(any("administrator approval" in line for line in lines))

    def test_official_patches_run_elevated(self):
        _, local, elevated, _, _ = self.run_install(patches=[("1.2", "C:\\hgpatc12.exe", "0" * 64)])
        local.assert_not_called()
        request = elevated.call_args.args[0]
        self.assertEqual((request["operation"], request["patches"][0][0]), ("official", "1.2"))

    def test_cutscene_support_runs_elevated(self):
        _, local, elevated, _, _ = self.run_install(install_media=True)
        local.assert_not_called()
        self.assertEqual(elevated.call_args.args[0]["operation"], "project")


class PlayTests(Temp):
    def test_describe_game_reports_version_renderer_and_resolution(self):
        game = make_game(self.root / "game")
        (game / "PLUGIN").mkdir()
        for name in (backend.HG_RENDERER, "DX5DRAW.DLL"):
            (game / "PLUGIN" / name).write_bytes(b"plugin")
        installer_core.write_setting(game / "DLLFILE.INI", backend.HG_RENDERER)
        installer_core.write_setting(game / "hgd3d9.res", "1280x960")
        with mock.patch.object(installer_core.hgfix, "game_version", return_value="1.2"):
            info = self.backend.describe_game(str(game))
        self.assertEqual((info.found, info.version, info.renderer, info.resolution),
                         (True, "1.2", backend.HG_RENDERER, "1280x960"))
        self.assertEqual(info.renderers, ["3dfx_hgd3d9.dll", "DX5DRAW.DLL"])
        self.assertFalse(self.backend.describe_game(str(self.root / "missing")).found)

    def test_find_game_uses_the_remembered_folder_then_the_registry(self):
        game = make_game(self.root / "game")
        with mock.patch.object(backend_windows, "get_game_path_from_registry", return_value=None):
            self.assertEqual(self.backend.find_game({"game_path": str(game)}), str(game))
            self.assertIsNone(self.backend.find_game({"game_path": str(self.root / "gone")}))
            self.assertEqual(self.backend.default_location({"game_path": str(self.root / "gone")}),
                             str(self.root / "gone"))
            self.assertTrue(self.backend.default_location({}).endswith("HeavyGear"))
        with mock.patch.object(backend_windows, "get_game_path_from_registry", return_value=game):
            self.assertEqual(self.backend.find_game({}), str(game))

    def test_resolution_validation(self):
        validate = backend.validate_resolution
        self.assertEqual(validate("320x240"), "320x240")
        self.assertEqual(validate("1920X1080"), "1920x1080")
        self.assertEqual(validate(""), "")
        for invalid in ("1920", "319x240", "7681x4320", "1920x0"):
            with self.assertRaises(ValueError, msg=invalid):
                validate(invalid)

    def test_plan_checks_the_renderer_and_the_red_menu_fix(self):
        game = make_game(self.root / "game")
        (game / "PLUGIN").mkdir()
        (game / "PLUGIN" / "DX5DRAW.DLL").write_bytes(b"plugin")
        with self.assertRaisesRegex(FileNotFoundError, "no longer installed"):
            self.backend.plan_apply(self.choices(renderer=backend.HG_RENDERER))
        with self.assertRaisesRegex(ValueError, "can't be turned off"):
            self.backend.plan_apply(self.choices(renderer="DX5DRAW.DLL"))
        (game / "PLUGIN" / backend.HG_RENDERER).write_bytes(b"plugin")
        with self.assertRaisesRegex(ValueError, "WIDTHxHEIGHT"):
            self.backend.plan_apply(self.choices(renderer=backend.HG_RENDERER, resolution="big"))
        plan = self.backend.plan_apply(self.choices(renderer=backend.HG_RENDERER, resolution="1920x1080"))
        self.assertEqual(plan["renderer_settings"], {"DLLFILE.INI": backend.HG_RENDERER, "hgd3d9.res": "1920x1080"})

    def test_plan_refuses_a_renderer_the_game_would_not_list(self):
        game = make_game(self.root / "game")
        (game / "PLUGIN").mkdir()
        for name in ("3dfxgear.dll", "i76draw.dll"):
            (game / "PLUGIN" / name).write_bytes(b"plugin")
        with mock.patch.object(installer_core, "find_glide_driver", return_value=None):
            with self.assertRaisesRegex(ValueError, "3Dfx needs a Glide driver"):
                self.backend.plan_apply(self.choices(renderer="3dfxgear.dll"))
            self.backend.plan_apply(self.choices(renderer="i76draw.dll"))          # Software 640: always offered
            (game / "glide2x.dll").write_bytes(b"driver")
            self.backend.plan_apply(self.choices(renderer="3dfxgear.dll"))

    def test_apply_writes_settings_and_elevates_on_permission_errors(self):
        nglide = mock.patch.object(backend_windows, "set_nglide_for_borderless", return_value=None)
        nglide.start()                                   # never the developer's real nGlide settings
        self.addCleanup(nglide.stop)
        game = make_game(self.root / "game")
        plan = {"game": game, "menu_fps": "30", "sim_fps": "60", "fixes": {"limiter": True, "dx5draw": False},
                "renderer_settings": {"DLLFILE.INI": backend.HG_RENDERER}}
        lines = []
        with mock.patch.object(installer_core, "apply_fixes", return_value="") as fixes:
            self.backend.apply(plan, lines.append)
        self.assertEqual(fixes.call_args.args[3:5], (["limiter"], ["dx5draw"]))
        self.assertEqual(lines, ["Community fixes applied."])
        self.assertEqual((game / "DLLFILE.INI").read_bytes(), b"3dfx_hgd3d9.dll\r\n")
        with mock.patch.object(installer_core, "apply_fixes", side_effect=PermissionError), \
                mock.patch.object(installer_core, "write_setting", side_effect=PermissionError), \
                mock.patch.object(backend_windows, "run_elevated_config", return_value="ok") as elevated:
            self.backend.apply(plan, lines.append)
        self.assertEqual([call.args[0]["operation"] for call in elevated.call_args_list], ["fixes", "settings"])

    def test_write_setting_keeps_a_backup_and_clears_read_only(self):
        setting = self.root / "hgd3d9.res"
        setting.write_bytes(b"1280x960\r\n")
        installer_core.write_setting(setting, "1920x1080")
        self.assertEqual(setting.read_bytes(), b"1920x1080\r\n")
        self.assertEqual(Path(str(setting) + ".hglauncher.bak").read_bytes(), b"1280x960\r\n")
        readonly = self.root / "readonly.ini"
        readonly.write_bytes(b"old renderer\r\n")
        os.chmod(readonly, readonly.stat().st_mode & ~stat.S_IWRITE)
        installer_core.write_setting(readonly, backend.HG_RENDERER)
        self.assertEqual(readonly.read_bytes(), b"3dfx_hgd3d9.dll\r\n")
        installer_core.write_setting(setting, "")
        self.assertFalse(setting.exists())

    def test_play_starts_the_game_in_its_folder_and_cannot_stop_it(self):
        game = make_game(self.root / "game")
        with mock.patch.object(backend_windows.subprocess, "Popen") as popen:
            self.backend.play({"game": game}, lambda line: None)
        popen.assert_called_once_with([str(game / "HG.EXE")], cwd=game)
        self.assertFalse(self.backend.can_stop)

    def test_nglide_is_used_only_for_borderless_3dfx(self):
        game = make_game(self.root / "game")
        (game / "glide2x.dll").write_bytes(b"MZ ... NGLIDE_RESOLUTION ...")
        (game / "DLLFILE.INI").write_bytes(b"3dfxgear.dll")
        with mock.patch.object(installer_core, "find_glide_driver", return_value=None):
            self.assertFalse(backend_windows.uses_nglide_borderless(game))          # not borderless
            (game / "HGSHELL.DLL").write_bytes(b"MZ .hgbdr")
            self.assertTrue(backend_windows.uses_nglide_borderless(game))
            (game / "DLLFILE.INI").write_bytes(b"3dfx_hgd3d9.dll")
            self.assertFalse(backend_windows.uses_nglide_borderless(game))          # another renderer
            (game / "DLLFILE.INI").write_bytes(b"3dfxgear.dll")
            (game / "glide2x.dll").write_bytes(b"MZ dgVoodoo")
            self.assertFalse(backend_windows.uses_nglide_borderless(game))          # another Glide driver

    def test_nglide_settings_are_saved_only_when_they_differ(self):
        values = {"Resolution": "1", "Aspect": "0", "Vsync": "1"}
        winreg = mock.MagicMock(REG_SZ=1)
        winreg.QueryValueEx.side_effect = lambda _key, name: (values[name], 1)
        winreg.SetValueEx.side_effect = lambda _key, name, _reserved, _type, value: values.update({name: value})
        with mock.patch.dict(sys.modules, {"winreg": winreg}), \
                mock.patch.object(backend_windows, "uses_nglide_borderless", return_value=True):
            self.assertIn("every game", backend_windows.set_nglide_for_borderless(self.root))
            self.assertIsNone(backend_windows.set_nglide_for_borderless(self.root))     # already set
        self.assertEqual(values, {"Resolution": "1", "Aspect": "1", "Vsync": "1"})   # the others untouched
        self.assertEqual(winreg.CreateKeyEx.call_args.args[1], r"Software\Zeus Software\nGlide2")
        winreg.SetValueEx.assert_called_once()
        with mock.patch.dict(sys.modules, {"winreg": winreg}), \
                mock.patch.object(backend_windows, "uses_nglide_borderless", return_value=False):
            self.assertIsNone(backend_windows.set_nglide_for_borderless(self.root))


if __name__ == "__main__":
    unittest.main()
