import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import launcher_settings
import win_system


def make_font(directory, filename, family, style, full=None):
    records = [(1, family), (2, style)] + ([(4, full)] if full else [])
    strings, entries = b"", b""
    for name_id, text in records:
        raw = text.encode("utf-16-be")
        entries += struct.pack(">HHHHHH", 3, 1, 0x0409, name_id, len(raw), len(strings))
        strings += raw
    table = struct.pack(">HHH", 0, len(records), 6 + len(entries)) + entries + strings
    font = bytearray(28 + len(table))
    struct.pack_into(">H", font, 4, 1)
    font[12:16] = b"name"
    struct.pack_into(">II", font, 20, 28, len(table))
    font[28:] = table
    path = Path(directory) / filename
    path.write_bytes(font)
    return path


class FontTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_fonts_sharing_a_family_get_distinct_registry_names(self):
        # Mirrors the two fonts on disc 1: same family, full names differ.
        regular = make_font(self.directory.name, "A.TTF", "SerpentineDBol", "Regular", "SerpentineDBol")
        italic = make_font(self.directory.name, "B.TTF", "SerpentineDBol", "Italic", "SerpentineDBol Italic")
        self.assertEqual(win_system.font_registry_name(regular), "SerpentineDBol (TrueType)")
        self.assertEqual(win_system.font_registry_name(italic), "SerpentineDBol Italic (TrueType)")
        plan = win_system.plan_font_installs([regular, italic], Path(self.directory.name, "fonts"), {})
        self.assertEqual(len(plan), 2)

    def test_registry_name_falls_back_to_family_and_style(self):
        bold = make_font(self.directory.name, "C.TTF", "Foo", "Bold")
        self.assertEqual(win_system.font_registry_name(bold), "Foo Bold (TrueType)")

    def test_identical_full_names_are_rejected_before_anything_is_installed(self):
        one = make_font(self.directory.name, "A.TTF", "Foo", "Regular")
        two = make_font(self.directory.name, "B.TTF", "Foo", "Regular")
        with self.assertRaisesRegex(ValueError, "same font name"):
            win_system.plan_font_installs([one, two], Path(self.directory.name, "fonts"), {})

    def test_other_files_registered_or_installed_under_the_name_are_not_replaced(self):
        font = make_font(self.directory.name, "A.TTF", "Foo", "Regular")
        fonts = Path(self.directory.name, "fonts")
        with self.assertRaisesRegex(FileExistsError, "already registered as 'other.ttf'"):
            win_system.plan_font_installs([font], fonts, {"Foo (TrueType)": "other.ttf"})
        fonts.mkdir()
        (fonts / "A.TTF").write_bytes(b"different")
        with self.assertRaisesRegex(FileExistsError, "different font"):
            win_system.plan_font_installs([font], fonts, {})


class RegistrationTests(unittest.TestCase):
    def test_same_or_stale_registration_is_not_a_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            other = Path(temporary) / "other"
            game.mkdir()
            other.mkdir()
            self.assertIsNone(win_system.registration_conflict(None, game))
            self.assertIsNone(win_system.registration_conflict(str(game / "HG.EXE"), game))
            self.assertIsNone(win_system.registration_conflict(str(other / "HG.EXE"), game))  # stale
            (other / "HG.EXE").write_bytes(b"x")
            self.assertEqual(
                win_system.registration_conflict(str(other / "HG.EXE"), game), str(other / "HG.EXE")
            )


    def test_leftover_newer_version_is_stale_for_a_disc_game_only(self):
        self.assertEqual(win_system.stale_version_subkeys(["1.2", "1.00"], "1.0"), ["1.2"])
        self.assertEqual(win_system.stale_version_subkeys(["1.87"], "1.0"), ["1.87"])
        self.assertEqual(win_system.stale_version_subkeys(["1.2"], "1.2"), [])
        self.assertEqual(win_system.stale_version_subkeys(["1.2"], None), [])


def make_x86_dll(path):
    image = bytearray(128)
    image[:2] = b"MZ"
    image[0x3C:0x40] = (64).to_bytes(4, "little")
    image[64:68] = b"PE\0\0"
    image[68:70] = (0x014C).to_bytes(2, "little")
    image[86:88] = (0x2000).to_bytes(2, "little")
    Path(path).write_bytes(bytes(image))
    return Path(path)


class IndeoCodecTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        system = self.root / "system"
        system.mkdir()
        self.disc = self.root / "disc1"
        (self.disc / "INSTALL" / "DATA").mkdir(parents=True)
        (self.disc / "INSTALL" / "DATA" / "HG.EXE").write_bytes(b"x")
        (self.disc / "INSTALL" / "DATA1.CAB").write_bytes(b"cab")
        patcher = mock.patch.object(win_system, "_system_directory", return_value=system)
        patcher.start()
        self.addCleanup(patcher.stop)

    def unshield(self, available):
        def run(command, **_kwargs):
            folder = Path(command[command.index("-d") + 1]) / "Root"
            folder.mkdir()
            make_x86_dll(folder / "Ir50_32.dll")
        return mock.patch.multiple(
            win_system,
            shutil=mock.Mock(which=mock.Mock(return_value="/usr/bin/unshield" if available else None)),
            subprocess=mock.Mock(run=mock.Mock(side_effect=run)),
        )

    def test_unshield_extracts_the_codec_from_disc_1(self):
        workdir = self.root / "work"
        workdir.mkdir()
        with self.unshield(True):
            codec = win_system.resolve_indeo_codec(None, str(self.disc), workdir)
            self.assertEqual(codec.name, "Ir50_32.dll")
            self.assertEqual(workdir, codec.parent.parent)
            win_system.subprocess.run.assert_called_once()

    def test_without_unshield_the_selected_file_is_used(self):
        selected = make_x86_dll(self.root / "ir50_32.dll")
        with self.unshield(False):
            self.assertEqual(win_system.resolve_indeo_codec(str(selected), str(self.disc)), selected.resolve())
            win_system.subprocess.run.assert_not_called()

    def test_without_unshield_or_a_file_both_remedies_are_named(self):
        with self.unshield(False):
            with self.assertRaisesRegex(FileNotFoundError, "unshield.*ir50_32.dll"):
                win_system.resolve_indeo_codec(None, str(self.disc))

    def test_a_failed_extraction_falls_back_to_the_selected_file(self):
        selected = make_x86_dll(self.root / "ir50_32.dll")
        workdir = self.root / "work"
        workdir.mkdir()
        with self.unshield(True):
            win_system.subprocess.run.side_effect = None          # unshield finds nothing
            self.assertEqual(win_system.resolve_indeo_codec(str(selected), str(self.disc), workdir),
                             selected.resolve())
            with self.assertRaisesRegex(FileNotFoundError, "unshield did not find"):
                win_system.resolve_indeo_codec(None, str(self.disc), workdir)

    def test_an_installed_codec_wins(self):
        self.assertFalse(win_system.indeo_installed())
        installed = make_x86_dll(win_system._system_directory() / "ir50_32.dll")
        self.assertTrue(win_system.indeo_installed())
        with self.unshield(True):
            self.assertEqual(win_system.resolve_indeo_codec(None, str(self.disc)), installed)


class SettingsTests(unittest.TestCase):
    FIXES = {"limiter": True, "palette": False}

    def test_round_trip_and_bad_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sub" / "launcher.json"
            self.assertEqual(launcher_settings.load_settings(self.FIXES, path), {})
            saved = {"game_path": "D:/HG", "menu_fps": "60", "sim_fps": "30",
                     "fixes": {"limiter": False, "palette": True}}
            self.assertTrue(launcher_settings.save_settings(saved, path))
            self.assertEqual(launcher_settings.load_settings(self.FIXES, path), saved)
            path.write_text('{"menu_fps": "999", "fixes": {"nope": true, "limiter": "yes"}}')
            self.assertEqual(launcher_settings.load_settings(self.FIXES, path), {"fixes": {}})
            path.write_text("not json")
            self.assertEqual(launcher_settings.load_settings(self.FIXES, path), {})


if __name__ == "__main__":
    unittest.main()
