import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import installer_core  # noqa: F401  (puts the bundled patcher on sys.path)
import hgfix


class NoDiscTests(unittest.TestCase):
    def make_disc2(self, root):
        video = root / "VIDEO"
        video.mkdir(parents=True)
        (video / "B51MOVIE.AVI").write_bytes(b"intro")
        (video / "ZL_CUT01.AVI").write_bytes(b"cut")
        return root

    def test_fix_is_off_by_default_on_every_platform(self):
        for platform in ("windows", "wine"):
            self.assertNotIn("nodisc", hgfix.choose_fixes(platform, [], []))
        self.assertIn("nodisc", hgfix.choose_fixes("windows", ["nodisc"], []))

    def test_every_version_has_a_complete_profile(self):
        for version, profile in hgfix.PROFILES.items():
            nodisc = profile["nodisc"]
            self.assertTrue(nodisc["shell"], version)
            self.assertEqual({"shell", "drives", "drives_iat", "sep", "sim_cmp", "sim_path"}, set(nodisc))

    def test_the_fake_drive_list_routine_is_position_independent_and_pops_its_arguments(self):
        code = hgfix.NODISC_DRIVES
        self.assertEqual(bytes.fromhex("8b442408"), code[:4])         # mov eax,[esp+8]: the buffer
        self.assertEqual(bytes.fromhex("c20800"), code[-3:])         # ret 8 (stdcall, two arguments)
        self.assertIn(b"." + b"\\" + bytes(2), code)                      # the single entry (a backslash) in a 4-byte slot
        for profile in hgfix.PROFILES.values():
            nodisc = profile["nodisc"]
            self.assertEqual(len(nodisc["shell"]), len(nodisc["drives"]))   # one drive-list call per scan
            self.assertTrue(nodisc["drives_iat"])

    def test_replacement_strings_fit_their_slots(self):
        old, new = hgfix.NODISC_SHELL_FMT
        self.assertEqual(len(old), len(new))
        old, new = hgfix.NODISC_CMP
        self.assertEqual(len(old), len(new))
        old, new = hgfix.NODISC_SEP            # the last scan's caller joins letter + separator + folder name
        self.assertEqual(len(old), len(new))
        self.assertEqual(b":", old[:1])
        self.assertNotIn(b":", new)
        # the sim's probe path may grow into the zero padding, and its first byte is the drive letter
        old, new = hgfix.NODISC_SIM_PATH
        self.assertLessEqual(len(new) - len(old), 2)
        self.assertEqual(b" ", new[:1])

    def test_videos_are_copied_from_a_disc_or_its_video_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disc = self.make_disc2(root / "disc2")
            for source in (disc, disc / "VIDEO"):
                game = root / f"game-{source.name}"
                game.mkdir()
                note = hgfix.copy_videos(str(game), str(source))
                self.assertIn("2 file(s) copied", note)
                self.assertTrue((game / "VIDEO" / "B51MOVIE.AVI").is_file())

    def test_existing_videos_are_kept_and_a_wrong_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disc = self.make_disc2(root / "disc2")
            game = root / "game"
            (game / "video").mkdir(parents=True)
            (game / "video" / "B51MOVIE.AVI").write_bytes(b"mine")
            self.assertIn("1 file(s) copied", hgfix.copy_videos(str(game), str(disc)))
            self.assertEqual(b"mine", (game / "video" / "B51MOVIE.AVI").read_bytes())
            with self.assertRaises(SystemExit):
                hgfix.copy_videos(str(game), str(root))

    def test_missing_videos_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIn("WARNING", hgfix.copy_videos(temporary, None))


class DisplayFixTests(unittest.TestCase):
    def test_the_wine_display_fix_is_never_applied_on_windows(self):
        self.assertNotIn("display", hgfix.choose_fixes("windows", ["display"], []))
        self.assertIn("display", hgfix.choose_fixes("wine", [], []))
        self.assertIn("display", hgfix.choose_fixes("wine", ["display"], []))


class Movie32Tests(unittest.TestCase):
    def test_on_by_default_on_windows_only_and_can_be_skipped(self):
        self.assertIn("movie32", hgfix.choose_fixes("windows", [], []))
        self.assertNotIn("movie32", hgfix.choose_fixes("wine", [], []))
        self.assertNotIn("movie32", hgfix.choose_fixes("windows", [], ["movie32"]))

    def test_every_version_has_the_call_site_and_the_edit_keeps_its_length(self):
        old, new = hgfix.MOVIE32
        self.assertEqual(len(old), len(new))
        self.assertEqual(bytes([0x6A, 32]), new)                      # push 32 (bits per pixel)
        for version, profile in hgfix.PROFILES.items():
            self.assertTrue(profile["movie32"], version)

    def test_the_patch_checks_the_bytes_before_it_changes_them(self):
        class Fake:
            def __init__(self, data):
                self.d, self.base = bytearray(data), 0

            def off(self, va):
                return va

        with mock.patch.dict(hgfix.PROFILES, {"t": {"movie32": 4}}):
            good = Fake(bytes(4) + bytes([0x6A, 16]) + bytes(4))
            hgfix.patch_movie32(good, "t")
            self.assertEqual(bytes([0x6A, 32]), bytes(good.d[4:6]))
            with self.assertRaises(SystemExit):
                hgfix.patch_movie32(Fake(bytes(10)), "t")


class MusicTests(unittest.TestCase):
    def test_music_turns_on_nodisc_but_is_off_by_default(self):
        self.assertNotIn("music", hgfix.choose_fixes("windows", [], []))
        self.assertIn("music", hgfix.choose_fixes("windows", ["music"], []))

    def test_allowed_imports_match_the_proxy_exports(self):
        defs = (Path(__file__).resolve().parent.parent / "tools" / "cdaudio" / "exports.def").read_text()
        exported = {line.split("=")[0] for line in defs.splitlines()[2:] if "=" in line}
        self.assertEqual(exported, hgfix.HGCD_EXPORTS)

    def test_proxy_name_fits_the_import_slot(self):
        self.assertLessEqual(len(hgfix.PROXY_NAME), len("WINMM.dll"))

    def test_track_files_are_copied_from_a_rip_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rip = root / "rip"
            rip.mkdir()
            for name in ("Track02.wav", "TRACK3.MP3", "notes.txt", "track.wav", "Track02.cue"):
                (rip / name).write_bytes(b"x")
            game = root / "game"
            game.mkdir()
            self.assertIn("2 track file(s) copied", hgfix.copy_music(str(game), str(rip)))
            self.assertEqual({"Track02.wav", "TRACK3.MP3"}, {p.name for p in (game / "MUSIC").iterdir()})
            self.assertIsNone(hgfix.copy_music(str(game), None))
            with self.assertRaises(SystemExit):
                hgfix.copy_music(str(game), str(root))

    def test_missing_track_files_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIn("WARNING", hgfix.copy_music(temporary, None))

    def test_a_built_proxy_passes_the_check_and_other_files_do_not(self):
        built = Path(__file__).resolve().parent.parent / "tools" / "cdaudio" / "hgcd.dll"
        if built.is_file():
            self.assertIsNone(hgfix.proxy_problem(str(built)))
            with mock.patch.object(hgfix, "HGCD_EXPORTS", hgfix.HGCD_EXPORTS | {"noSuchExport"}):
                self.assertIn("noSuchExport", hgfix.proxy_problem(str(built)))
        self.assertIn("not a valid DLL", hgfix.proxy_problem(__file__))
        self.assertIn("not a valid DLL", hgfix.proxy_problem(__file__ + ".missing"))

    def test_a_usable_proxy_is_preferred_to_a_broken_one_in_the_game_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool").mkdir()
            (root / "game").mkdir()
            (root / "tool" / "hgcd.dll").write_bytes(b"good")
            (root / "game" / "hgcd.dll").write_bytes(b"x")
            game = str(root / "game")
            with mock.patch.object(hgfix, "proxy_problem", side_effect=lambda path: "broken" if path.startswith(game) else None), \
                    mock.patch.object(hgfix, "__file__", str(root / "tool" / "hgfix.py")):
                self.assertEqual(str(root / "tool" / "hgcd.dll"), hgfix.find_proxy(game, None))
            # with nothing usable anywhere, the broken one is handed back so the caller can say what is wrong with it
            (root / "tool" / "hgcd.dll").unlink()
            with mock.patch.object(hgfix, "proxy_problem", return_value="broken"), \
                    mock.patch.object(hgfix, "__file__", str(root / "tool" / "hgfix.py")):
                self.assertEqual(str(root / "game" / "hgcd.dll"), hgfix.find_proxy(game, None))

    def test_a_newer_proxy_beside_the_patcher_wins_over_the_one_in_the_game_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool").mkdir()
            (root / "game").mkdir()
            (root / "tool" / "hgcd.dll").write_bytes(b"new")
            (root / "game" / "hgcd.dll").write_bytes(b"old")
            with mock.patch.object(hgfix, "proxy_problem", return_value=None),                     mock.patch.object(hgfix, "__file__", str(root / "tool" / "hgfix.py")):
                self.assertEqual(str(root / "tool" / "hgcd.dll"), hgfix.find_proxy(str(root / "game"), None))

    def test_proxy_is_found_where_it_is_said_to_be(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            given = root / "mine.dll"
            given.write_bytes(b"x")
            self.assertEqual(str(given), hgfix.find_proxy(str(root), str(given)))
            with self.assertRaises(SystemExit):
                hgfix.find_proxy(str(root), str(root / "missing.dll"))
            (root / "hgcd.dll").write_bytes(b"x")
            (root / "tool").mkdir()
            with mock.patch.object(hgfix, "proxy_problem", return_value=None),                     mock.patch.object(hgfix, "__file__", str(root / "tool" / "hgfix.py")):
                self.assertEqual(str(root / "hgcd.dll"), hgfix.find_proxy(str(root), None))


if __name__ == "__main__":
    unittest.main()
