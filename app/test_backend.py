import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backend

HGFIX = Path(backend.__file__).resolve().parent.parent / "patcher" / "hgfix.py"


def listed_defaults(platform):
    """The fixes `hgfix.py --list` ticks for a platform."""
    output = subprocess.run(
        [sys.executable, str(HGFIX), ".", "--list", "--platform", platform],
        capture_output=True, text=True, check=True,
    ).stdout
    return set(re.findall(r"^\s*\[x\]\s+(\S+)", output, re.MULTILINE))


class FixListTests(unittest.TestCase):
    def test_every_offered_fix_is_a_patcher_fix_with_a_label(self):
        for platform in ("wine", "windows"):
            for fix in backend.fixes(platform):
                self.assertIn(fix.name, backend.hgfix.FIXES)
                self.assertTrue(fix.label and fix.description)

    def test_particle_depth_is_offered_unticked_until_1_2(self):
        for platform in ("wine", "windows"):
            offered = {fix.name: fix for fix in backend.fixes(platform)}
            self.assertIn("partdepth", offered)
            self.assertFalse(offered["partdepth"].default)
            offered_12 = {fix.name: fix for fix in backend.fixes(platform, "1.2")}
            self.assertTrue(offered_12["partdepth"].default)
            self.assertTrue(offered_12["borderless"].default)

    def test_defaults_equal_the_patchers_list(self):
        for platform in ("wine", "windows"):
            listed = listed_defaults(platform)
            for fix in backend.fixes(platform):
                self.assertEqual(fix.default, fix.name in listed, (platform, fix.name))

    def test_platform_only_fixes_are_offered_only_there(self):
        wine = {fix.name for fix in backend.fixes("wine")}
        windows = {fix.name for fix in backend.fixes("windows")}
        self.assertFalse({"dx5draw", "movie32", "nodisc", "music"} & wine)
        self.assertFalse({"display", "moviebg"} & windows)
        self.assertIn("borderless", windows)
        self.assertEqual({fix.section for fix in backend.fixes("wine")}, {"fixes"})
        self.assertEqual({fix.section for fix in backend.fixes("windows")}, {"fixes"})


if __name__ == "__main__":
    unittest.main()
