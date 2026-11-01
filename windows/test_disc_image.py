import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import disc2_media
import disc_image

SECTOR = 2448                  # raw sector plus 96 bytes of subchannel, as Alcohol 120% stores it


def make_image(folder, name="DISC", tracks=((10, 0, 20), (9, 170, 30), (9, 200, 25))):
    """A small .mds/.mdf pair: (mode nibble, start sector, length) per track, stored one after another; the
    150-sector gap before the first audio track is not in the file, as in real images."""
    mdf = bytearray()
    blocks, extras, offsets = [], [], []
    for number, (mode, start, length) in enumerate(tracks, 1):
        offsets.append(len(mdf))
        for lba in range(start, start + length):
            raw = bytearray(SECTOR)
            if mode == 10:
                raw[16:16 + 2048] = bytes([lba % 251]) * 2048           # user data marks its sector
            else:
                raw[:2352] = struct.pack("<H", lba) * 1176             # audio marks its sector
            mdf += raw
    header_size, session_size = 0x58, 24
    block_offset = header_size + session_size
    extra_offset = block_offset + 80 * len(tracks)
    for number, ((mode, start, length), offset) in enumerate(zip(tracks, offsets), 1):
        block = bytearray(80)
        block[0], block[4] = 0xA0 | mode, number
        struct.pack_into("<I", block, 0x0C, extra_offset + 8 * (number - 1))
        struct.pack_into("<H", block, 0x10, SECTOR)
        struct.pack_into("<IQ", block, 0x24, start, offset)
        blocks.append(bytes(block))
        extras.append(struct.pack("<II", 150 if number < 3 else 0, length))
    header = bytearray(header_size)
    header[:16] = b"MEDIA DESCRIPTOR"
    struct.pack_into("<H", header, 0x14, 1)
    struct.pack_into("<I", header, 0x50, header_size)
    session = struct.pack("<iiHBBHHII", -150, tracks[-1][1] + tracks[-1][2], 1, len(tracks), 0, 1, len(tracks), 0,
                          block_offset)
    (folder / f"{name}.mds").write_bytes(bytes(header) + session + b"".join(blocks) + b"".join(extras))
    (folder / f"{name}.MDF").write_bytes(bytes(mdf))
    return folder / f"{name}.mds"


class MdsImageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_the_table_of_contents_reads_like_a_drives(self):
        with disc_image.MdsImage(make_image(self.root)) as image:
            entries = disc2_media.parse_toc(image.read_toc())
            self.assertEqual(entries, [(1, False, 0), (2, True, 170), (3, True, 200), (0xAA, False, 225)])
            self.assertEqual(disc2_media.audio_tracks(entries), [(2, 170, 200), (3, 200, 225)])

    def test_audio_sectors_come_back_raw_and_in_place(self):
        with disc_image.MdsImage(make_image(self.root)) as image:
            data = image.read_audio(198, 4)                    # crosses from track 2 into track 3
            self.assertEqual(len(data), 2 * 2352)              # stops at the end of the track it started in
            self.assertEqual(data[:2], struct.pack("<H", 198))
            self.assertEqual(image.read_audio(200, 1)[:2], struct.pack("<H", 200))
            self.assertEqual(image.read_audio(160, 16), b"\0" * 10 * 2352)    # the unstored gap: silence to 170
            with self.assertRaises(OSError):
                image.read_audio(225, 1)                       # past the last track

    def test_a_gap_between_audio_tracks_rips_as_silence_not_errors(self):
        tracks = ((10, 0, 20), (9, 170, 30), (9, 210, 25))     # 10 unstored sectors before track 3
        with disc_image.MdsImage(make_image(self.root, tracks=tracks)) as image:
            _number, start, end = disc2_media.audio_tracks(disc2_media.parse_toc(image.read_toc()))[0]
            self.assertEqual(disc2_media.rip_track(image, start, end, self.root / "TRACK02.WAV"), 0)

    def test_the_data_track_becomes_an_iso(self):
        with disc_image.MdsImage(make_image(self.root)) as image:
            iso = image.write_iso(self.root / "disc.iso").read_bytes()
        self.assertEqual(len(iso), 20 * 2048)
        self.assertEqual([iso[n * 2048] for n in range(20)], [n % 251 for n in range(20)])

    def test_either_file_of_the_pair_opens_it(self):
        mds = make_image(self.root)
        with disc_image.MdsImage(mds.with_suffix(".MDF")) as image:
            self.assertEqual(len(image.tracks), 3)
        self.assertTrue(disc_image.is_mds("x.MDF") and disc_image.is_mds("x.mds"))
        self.assertFalse(disc_image.is_mds("x.iso"))

    def test_a_missing_half_or_a_wrong_file_is_refused(self):
        mds = make_image(self.root)
        mds.with_suffix(".MDF").unlink()
        with self.assertRaisesRegex(disc_image.ImageError, "both its .mds and .mdf"):
            disc_image.MdsImage(mds)
        (self.root / "OTHER.mds").write_bytes(b"not a descriptor")
        (self.root / "OTHER.mdf").write_bytes(b"")
        with self.assertRaisesRegex(disc_image.ImageError, "not an Alcohol 120% descriptor"):
            disc_image.MdsImage(self.root / "OTHER.mds")
        cut = make_image(self.root, name="CUT")
        cut.write_bytes(cut.read_bytes()[:0x58 + 24 + 10])            # the track blocks are missing
        with self.assertRaisesRegex(disc_image.ImageError, "cut short or damaged"):
            disc_image.MdsImage(cut)


if __name__ == "__main__":
    unittest.main()
