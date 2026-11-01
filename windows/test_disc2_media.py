import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import disc2_media
import installer_core

SECTOR = disc2_media.SECTOR_BYTES


def setUpModule():
    # The real check looks for a running HG.EXE: the tests must not depend on whether the developer is playing.
    patcher = mock.patch.object(installer_core, "ensure_game_not_running")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def msf(lba):
    total = lba + disc2_media.PRE_GAP
    return (0, total // 75 // 60, total // 75 % 60, total % 75)


def make_toc(tracks):
    """tracks: [(number, is_audio, lba)], the lead-out last, as the drive reports them."""
    body = b""
    for number, is_audio, lba in tracks:
        body += bytes((0, 0x10 if is_audio else 0x14, number, 0)) + bytes(msf(lba))
    first = tracks[0][0]
    last = max(number for number, _a, _l in tracks if number != 0xAA)
    return struct.pack(">HBB", len(body) + 2, first, last) + body


class FakeDrive:
    """Sector n holds the byte n % 251 everywhere; sectors in `bad` cannot be read."""

    def __init__(self, toc, bad=(), no_audio=False):
        self.toc, self.bad, self.no_audio = toc, set(bad), no_audio
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def read_toc(self):
        return self.toc

    def read_audio(self, lba, count):
        if self.no_audio or any(s in self.bad for s in range(lba, lba + count)):
            raise OSError(21, "not ready")
        return b"".join(bytes([s % 251]) * SECTOR for s in range(lba, lba + count))


MIXED = [(1, False, 0), (2, True, 1000), (3, True, 1600), (0xAA, False, 2000)]


class TocTests(unittest.TestCase):
    def test_toc_is_parsed_into_numbers_kinds_and_sector_addresses(self):
        entries = disc2_media.parse_toc(make_toc(MIXED))
        self.assertEqual([(1, False, 0), (2, True, 1000), (3, True, 1600), (0xAA, False, 2000)], entries)

    def test_audio_tracks_of_a_mixed_disc_end_at_the_next_track(self):
        tracks = disc2_media.audio_tracks(disc2_media.parse_toc(make_toc(MIXED)))
        self.assertEqual([(2, 1000, 1600), (3, 1600, 2000)], tracks)

    def test_cd_extra_audio_stops_before_the_data_session(self):
        extra = [(1, True, 0), (2, True, 20000), (3, False, 50000), (0xAA, False, 60000)]
        tracks = disc2_media.audio_tracks(disc2_media.parse_toc(make_toc(extra)))
        self.assertEqual([(1, 0, 20000), (2, 20000, 50000 - disc2_media.EXTRA_GAP)], tracks)

    def test_an_empty_answer_is_a_message_for_the_user(self):
        with self.assertRaises(disc2_media.RipError):
            disc2_media.parse_toc(b"")


class RipTests(unittest.TestCase):
    def test_a_track_becomes_a_cd_quality_wav(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "t.wav"
            seen = []
            bad = disc2_media.rip_track(FakeDrive(b""), 100, 140, path, seen.append)
            self.assertEqual(0, bad)
            self.assertEqual(1.0, seen[-1])
            with wave.open(str(path)) as wav:
                self.assertEqual((2, 2, 44100), (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()))
                self.assertEqual(40 * SECTOR // 4, wav.getnframes())
                self.assertEqual(bytes([100]) * SECTOR, wav.readframes(SECTOR // 4))

    def test_an_unreadable_sector_becomes_silence_and_the_rest_is_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "t.wav"
            bad = disc2_media.rip_track(FakeDrive(b"", bad={105}), 100, 140, path)
            self.assertEqual(1, bad)
            with wave.open(str(path)) as wav:
                self.assertEqual(40 * SECTOR // 4, wav.getnframes())
                data = wav.readframes(wav.getnframes())
            self.assertEqual(b"\0" * SECTOR, data[5 * SECTOR : 6 * SECTOR])
            self.assertEqual(bytes([106]) * SECTOR, data[6 * SECTOR : 7 * SECTOR])

    def test_a_drive_that_cannot_read_audio_is_reported_not_ripped_as_silence(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(disc2_media.RipError):
                disc2_media.rip_track(FakeDrive(b"", no_audio=True), 100, 400, Path(temporary) / "t.wav")

    def test_every_audio_track_is_written_under_its_disc_track_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            drive = FakeDrive(make_toc(MIXED))
            lines = []
            ripped = disc2_media.rip_audio("D:\\", Path(temporary) / "MUSIC", lines.append, opener=lambda root: drive)
            self.assertEqual(["TRACK02.WAV", "TRACK03.WAV"], sorted(p.name for p in (Path(temporary) / "MUSIC").iterdir()))
            self.assertEqual([2, 3], [number for number, _path, _bad in ripped])
            self.assertTrue(drive.closed)
            self.assertTrue(any("Track 2" in line for line in lines))

    def test_a_disc_without_audio_is_refused(self):
        data_only = make_toc([(1, False, 0), (0xAA, False, 500)])
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(disc2_media.RipError):
                disc2_media.rip_audio("D:", temporary, opener=lambda root: FakeDrive(data_only))


class FindDiscTests(unittest.TestCase):
    def test_disc_2_is_recognised_by_its_video_folder_whatever_the_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Video").mkdir()
            (root / "Video" / "b51movie.avi").write_bytes(b"x")
            self.assertEqual(root, disc2_media.find_disc2(root))
            with self.assertRaises(FileNotFoundError):
                disc2_media.find_disc2(root / "Video")

    def test_a_copy_inside_a_project_folder_is_found(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "HG-DISC-2" / "VIDEO").mkdir(parents=True)
            (root / "HG-DISC-2" / "VIDEO" / "B51MOVIE.AVI").write_bytes(b"x")
            self.assertEqual(root / "HG-DISC-2", disc2_media.find_disc2(root))

    def test_drive_letters_are_normalised(self):
        self.assertEqual("D:\\", disc2_media.drive_root("d:"))
        self.assertEqual("D:\\", disc2_media.drive_root(" D:/ "))
        self.assertEqual("C:\\Games\\disc", disc2_media.drive_root("C:\\Games\\disc"))
        self.assertEqual("", disc2_media.drive_root(""))

    def test_detect_checks_each_cd_drive_for_the_video_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "VIDEO").mkdir()
            (root / "VIDEO" / "B51MOVIE.AVI").write_bytes(b"x")
            with mock.patch.object(disc2_media, "cd_drives", return_value=[str(root / "nothing"), str(root)]):
                self.assertEqual(str(root), disc2_media.detect_disc2())
            with mock.patch.object(disc2_media, "cd_drives", return_value=[]):
                self.assertEqual("", disc2_media.detect_disc2())


class ApplyFixesArgumentTests(unittest.TestCase):
    def test_disc_2_and_ripped_music_reach_the_patcher(self):
        with mock.patch.object(installer_core.hgfix, "main") as patcher:
            installer_core.apply_fixes("G", 30, 30, ["music"], [], "D:\\", "C:\\tmp\\music")
        args = patcher.call_args[0][0]
        self.assertEqual(["--disc2", "D:\\", "--music-from", "C:\\tmp\\music"], args[-4:])
        self.assertIn("music", args)

    def test_nothing_extra_is_passed_when_not_asked_for(self):
        with mock.patch.object(installer_core.hgfix, "main") as patcher:
            installer_core.apply_fixes("G")
        self.assertNotIn("--disc2", patcher.call_args[0][0])
        self.assertNotIn("--music-from", patcher.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
