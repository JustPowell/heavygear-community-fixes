import contextlib
import io
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import installer_core  # noqa: F401  (puts the bundled patcher on sys.path)
import hgfix


class BorderlessTests(unittest.TestCase):
    def test_default_on_only_for_1_2_and_applies_on_both_platforms(self):
        for platform in ("windows", "wine"):
            self.assertNotIn("borderless", hgfix.choose_fixes(platform, [], []))
            self.assertIn("borderless", hgfix.choose_fixes(platform, [], [], "1.2"))
        self.assertIn("borderless", hgfix.choose_fixes("wine", ["borderless"], []))
        self.assertIn("borderless", hgfix.choose_fixes("windows", ["borderless"], []))

    def test_it_replaces_display_moviebg_and_movie32(self):
        chosen = hgfix.choose_fixes("wine", ["borderless", "display", "movie32"], [])
        self.assertIn("borderless", chosen)
        self.assertFalse({"display", "moviebg", "movie32"} & chosen)
        self.assertIn("display", hgfix.choose_fixes("wine", [], []))      # untouched without it

    def test_list_shows_it_and_says_what_it_replaces(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hgfix.main(["unused", "--list", "--platform", "wine", "--fix", "borderless"])
        self.assertIn("[x] borderless", out.getvalue())
        self.assertIn("[ ] display", out.getvalue())

    def test_refused_for_v1_0(self):
        self.assertNotIn("borderless", hgfix.PROFILES["1.0"])
        with self.assertRaises(SystemExit):
            hgfix.patch_borderless(None, None, "1.0")

    def sites(self):
        b = hgfix.PROFILES["1.2"]["borderless"]
        shell = list(b["modes"]) + [b[k] for k in ("gate", "window", "present", "present_rect", "stretch_cmp",
                                                   "poll", "poll_rect", "mousemsg", "movie")]
        return shell + [hgfix.PROFILES["1.2"]["moviebg"]["va"]], b["exe"]

    def test_every_site_is_checked_before_anything_is_written(self):
        shell_sites, exe_site = self.sites()
        for bad in shell_sites + [exe_site]:
            pe, exe = mock.Mock(), mock.Mock()
            with mock.patch.object(hgfix, "matches", side_effect=lambda _pe, va, _old: va != bad), \
                 mock.patch.object(hgfix, "put") as put:
                with self.assertRaises(SystemExit, msg=hex(bad)):
                    hgfix.patch_borderless(pe, exe, "1.2")
            put.assert_not_called()
            pe.add_section.assert_not_called()
            pe.disable_reloc.assert_not_called()

    def test_every_site_is_written_when_all_match(self):
        shell_sites, exe_site = self.sites()
        pe, exe = mock.Mock(), mock.Mock()
        pe.add_section.return_value = 0x10400000
        with mock.patch.object(hgfix, "matches", return_value=True), mock.patch.object(hgfix, "put") as put:
            hgfix.patch_borderless(pe, exe, "1.2")
        written = {call.args[1] for call in put.call_args_list}
        self.assertLessEqual(set(shell_sites) | {exe_site}, written)
        self.assertEqual({hgfix.PROFILES["1.2"]["borderless"][k] + 2 for k in ("stretch_cmp", "poll")},
                         {call.args[0] for call in pe.disable_reloc.call_args_list})

    def test_every_sim_site_is_checked_before_anything_is_written(self):
        b = hgfix.PROFILES["1.2"]["borderless_sim"]
        for bad in [b["mode"], b["window"], b["winproc"]] + b["blits"]:
            pe = mock.Mock()
            with mock.patch.object(hgfix, "matches", side_effect=lambda _pe, va, _old: va != bad), \
                 mock.patch.object(hgfix, "put") as put:
                with self.assertRaises(SystemExit, msg=hex(bad)):
                    hgfix.patch_borderless_sim(pe, "1.2")
            put.assert_not_called()
            pe.add_section.assert_not_called()
        pe = mock.Mock()
        pe.add_section.return_value = 0x10400000
        with mock.patch.object(hgfix, "matches", return_value=True), mock.patch.object(hgfix, "put") as put:
            hgfix.patch_borderless_sim(pe, "1.2")
        self.assertLessEqual({b["mode"], b["window"], b["winproc"], *b["blits"]}, {call.args[1] for call in put.call_args_list})
        self.assertEqual({va + 2 for va in b["blits"]}, {call.args[0] for call in pe.disable_reloc.call_args_list})

    def test_code_addresses_the_image_relative_to_its_own_position(self):
        k = hgfix._Code(0x1000)
        k.getpc(hgfix.ECX)
        self.assertEqual(0x1005, k.here)                     # the address "call $+5" pushes
        k.m(b"\x8b", hgfix.EAX, hgfix.ECX, 0x2000)
        self.assertEqual(0x2000 - 0x1005, struct.unpack_from("<i", k.c, len(k.c) - 4)[0])

    def test_mouse_map_subtracts_the_pictures_offset(self):
        # x' = (x - left) * canvas / width: each axis loads the point, then "sub eax,[ecx+disp32]" of the rectangle's
        # left or top. An imul there (as once slipped in) sends every click to the canvas's top-right corner.
        sec = 0x10400000
        code, entries = hgfix.build_borderless(sec, hgfix.PROFILES["1.2"]["borderless"])
        start = entries["map"] - sec - hgfix.BL_CODE
        here = entries["map"] + 8                            # after "push esi; mov esi,eax; call $+5"
        for f, pos in ((0, hgfix.BL_RX), (4, hgfix.BL_RY)):
            load = code.index(bytes([0x8b, 0x46, f]), start)
            self.assertEqual(b"\x2b\x81" + struct.pack("<i", sec + pos - here), code[load + 3:load + 9], msg=f)

    def test_routines_fit_their_section(self):
        code, entries = hgfix.build_borderless(0x10400000, hgfix.PROFILES["1.2"]["borderless"])
        self.assertLessEqual(hgfix.BL_CODE + len(code), 0x400)
        self.assertEqual({"window", "present", "map", "poll", "mousemsg", "movie"}, set(entries))
        self.assertEqual(0x10400000 + hgfix.BL_CODE, entries["window"])
        code, entries = hgfix.build_borderless_sim(0x10400000, hgfix.PROFILES["1.2"]["borderless_sim"])
        self.assertLessEqual(hgfix.BL_CODE + len(code), 0x400)
        self.assertEqual({"window", "blit", "activate"}, set(entries))


if __name__ == "__main__":
    unittest.main()
