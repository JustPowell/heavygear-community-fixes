"""Alcohol 120% disc images (.mds descriptor + .mdf data) for Setup: the data track as an .iso Windows can mount,
and the audio tracks for the ripper in disc2_media, which reads an MdsImage just as it reads a drive.

The .mds layout (version 1.x, as documented by the cdemu/libmirage project): the header holds the offset of the
session blocks at 0x50; a session block (24 bytes) holds the number of its track blocks and their offset; a track
block (80 bytes) holds the track mode (low nibble: 9 audio, 10 mode 1, 11 mode 2, 12 mode 2 form 1, 13 form 2),
the point (track number, or
0xA0-0xA2 for lead-in entries), the offset of its extra block (pregap, length), the size of each stored sector, the
start sector and the offset of the track's first sector in the .mdf. The pregap is not stored in the file; a drive
would return it as audio, so reads there come back as silence.
"""

import struct
from pathlib import Path

RAW = 2352                     # a whole CD sector; .mdf stores it, often followed by 96 bytes of subchannel data
USER = 2048                    # the user data of a data sector
SECTORS_PER_CHUNK = 512


class ImageError(ValueError):
    pass


def is_mds(path):
    return str(path).strip().casefold().endswith((".mds", ".mdf"))


def _pair(path):
    """(.mds, .mdf) for either file of a pair (same name, any case, same folder)."""
    path = Path(path).expanduser()
    found = {}
    for suffix in (".mds", ".mdf"):
        wanted = (path.stem + suffix).casefold()
        found[suffix] = next((item for item in path.parent.iterdir() if item.name.casefold() == wanted), None)
    if not found[".mds"] or not found[".mdf"]:
        raise ImageError(f"'{path.name}' needs both its .mds and .mdf files in the same folder.")
    return found[".mds"], found[".mdf"]


class MdsImage:
    """An .mds/.mdf pair opened for reading: `with MdsImage(path) as image`. Tracks are
    (number, mode nibble, start sector, length, sector size, file offset), in disc order."""

    def __init__(self, path):
        self.mds, self.mdf = _pair(path)
        data = self.mds.read_bytes()
        if data[:16] != b"MEDIA DESCRIPTOR":
            raise ImageError(f"'{self.mds.name}' is not an Alcohol 120% descriptor (.mds).")
        try:
            tracks = []
            sessions, = struct.unpack_from("<H", data, 0x14)
            session_offset, = struct.unpack_from("<I", data, 0x50)
            for session in range(sessions):
                *_, blocks, _leadin, _first, _last, _unknown, block_offset = struct.unpack_from(
                    "<iiHBBHHII", data, session_offset + 24 * session)
                for index in range(blocks):
                    block = block_offset + 80 * index
                    mode, point = data[block] & 0x0F, data[block + 4]
                    if not 1 <= point <= 99:
                        continue
                    extra, = struct.unpack_from("<I", data, block + 0x0C)
                    size, = struct.unpack_from("<H", data, block + 0x10)
                    start, offset = struct.unpack_from("<IQ", data, block + 0x24)
                    _pregap, length = struct.unpack_from("<II", data, extra)
                    tracks.append((point, mode, start, length, size, offset))
        except (struct.error, IndexError) as exc:
            raise ImageError(f"'{self.mds.name}' is cut short or damaged.") from exc
        if not tracks:
            raise ImageError(f"'{self.mds.name}' lists no tracks.")
        self.tracks = sorted(tracks, key=lambda track: track[2])
        self._file = open(self.mdf, "rb")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None

    def _track(self, lba):
        for track in self.tracks:
            if track[2] <= lba < track[2] + track[3]:
                return track
        raise OSError(0, f"sector {lba} is not in the image")

    def _read(self, lba, count, skip, keep):
        """`count` sectors from `lba`, each cut to `keep` bytes from byte `skip`."""
        _n, _mode, start, length, size, offset = self._track(lba)
        count = min(count, start + length - lba)
        self._file.seek(offset + (lba - start) * size)
        data = self._file.read(count * size)
        if len(data) != count * size:
            raise OSError(0, "the .mdf file is shorter than its .mds says")
        if size == keep and not skip:
            return data
        return b"".join(data[at + skip:at + skip + keep] for at in range(0, len(data), size))

    # --- what disc2_media's ripper calls on a drive ------------------------------------------------
    def read_toc(self):
        """The table of contents in the drive's own format (READ TOC, format 0)."""
        def entry(number, data, lba):
            minutes, rest = divmod(lba + 150, 60 * 75)
            return bytes((0, 0x10 | (4 if data else 0), number, 0, 0, minutes, *divmod(rest, 75)))

        last = self.tracks[-1]
        body = b"".join(entry(number, mode != 9, start) for number, mode, start, *_ in self.tracks)
        body += entry(0xAA, False, last[2] + last[3])
        return struct.pack(">HBB", len(body) + 2, self.tracks[0][0], last[0]) + body

    def read_audio(self, lba, count):
        following = [track[2] for track in self.tracks if track[2] > lba]
        if not any(track[2] <= lba < track[2] + track[3] for track in self.tracks) and following:
            return b"\0" * RAW * min(count, following[0] - lba)          # a gap before a track: silence
        if self._track(lba)[4] < RAW:
            raise OSError(0, "this image stores no raw audio sectors")
        return self._read(lba, count, 0, RAW)

    # --- the data track ---------------------------------------------------------------------------
    def write_iso(self, destination):
        """Write the first data track's user data as an .iso. Returns its path."""
        track = next((track for track in self.tracks if track[1] != 9), None)
        if track is None:
            raise ImageError(f"'{self.mds.name}' has no data track.")
        _n, mode, start, length, size, _offset = track
        if size == USER:
            skip = 0
        elif size >= RAW and mode == 10:
            skip = 16                  # mode 1: 12 sync bytes and a 4-byte header
        elif size >= RAW and mode == 12:
            skip = 24                  # mode 2 form 1: also an 8-byte subheader
        else:
            raise ImageError(f"'{self.mds.name}': its data track's format (mode {mode}, {size}-byte sectors) "
                             "is not supported.")
        destination = Path(destination)
        with open(destination, "wb") as out:
            for lba in range(start, start + length, SECTORS_PER_CHUNK):
                out.write(self._read(lba, min(SECTORS_PER_CHUNK, start + length - lba), skip, USER))
        return destination
