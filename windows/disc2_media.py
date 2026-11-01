"""Disc 2 for Setup: find it, and rip its CD-audio soundtrack to TRACKnn.WAV files.

Disc 2 is a mixed disc: a data part (the VIDEO folder) and the soundtrack as CD audio. The data part is copied
by `hgfix --fix nodisc --disc2`; this module reads the audio tracks, which a file copy cannot reach. It talks to the
drive through the Windows CD-ROM IOCTLs (table of contents, then raw CD-DA sector reads) with only ctypes, so it
adds no dependency. The drive is wrapped in a small class so tests can use a fake one.
"""

import os
import struct
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent

SECTOR_BYTES = 2352            # one CD-DA sector: 588 stereo 16-bit frames
SECTORS_PER_READ = 16
SECTORS_PER_SECOND = 75
PRE_GAP = 150                  # the TOC counts from 2 seconds in; LBA 0 is that point
EXTRA_GAP = 11400              # audio sessions of a CD-Extra end this many sectors before the data session
LEAD_OUT = 0xAA
DRIVE_CDROM = 5
VIDEO_PROBE = ("VIDEO", "B51MOVIE.AVI")

IOCTL_CDROM_READ_TOC = 0x00024000
IOCTL_CDROM_RAW_READ = 0x0002403E
CDDA = 2                       # TRACK_MODE_TYPE


class RipError(RuntimeError):
    """A message for the user, not a traceback."""


# ----------------------------------------------------------------------------------------- finding disc 2
def _find(directory, parts):
    current = Path(directory)
    for part in parts:
        try:
            match = next(item for item in current.iterdir() if item.name.casefold() == part.casefold())
        except (OSError, StopIteration):
            return None
        current = match
    return current


def find_disc2(path):
    """The folder (or drive) holding disc 2's VIDEO folder; FileNotFoundError when `path` is not disc 2."""
    base = Path(path)
    for candidate in (base, base / "HG-DISC-2", base / "disc2"):
        if _find(candidate, VIDEO_PROBE):
            return candidate
    raise FileNotFoundError(
        "That is not Heavy Gear disc 2: VIDEO\\B51MOVIE.AVI was not found. Select the disc 2 drive "
        "or a folder copy of it."
    )


def cd_drives():
    """Drive roots (like 'D:\\') of the CD/DVD drives."""
    if os.name != "nt":
        return []
    import ctypes

    kernel32 = ctypes.windll.kernel32
    size = kernel32.GetLogicalDriveStringsW(0, None)
    buffer = ctypes.create_unicode_buffer(size + 1)
    kernel32.GetLogicalDriveStringsW(size, buffer)
    roots = [root for root in buffer[:size].split("\0") if root]
    return [root for root in roots if kernel32.GetDriveTypeW(root) == DRIVE_CDROM]


def is_cd_drive(path):
    root = str(path).strip().rstrip("\\/")
    return len(root) == 2 and root[1] == ":" and f"{root}\\".upper() in [d.upper() for d in cd_drives()]


def drive_root(path):
    """'D:' or 'd:/' -> 'D:\\'; anything else is returned unchanged."""
    text = str(path).strip()
    return f"{text[:1].upper()}:\\" if len(text.rstrip("\\/")) == 2 and text[1:2] == ":" else text


# --- disc images: Windows 8 and later mount an .iso as a CD drive, no administrator rights needed ----
def is_image(path):
    return str(path).strip().casefold().endswith(".iso")


def _powershell(script, image):
    """Run a PowerShell script with the image path in $env:HG_ISO (never pasted into the script)."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "HG_ISO": str(Path(image).resolve())}, capture_output=True, text=True, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise OSError(f"Windows could not mount '{image}': {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def mount_image(image):
    """Mount a disc image. Returns (drive root like 'E:\\', whether this call mounted it): an image that is
    already mounted is reused and left mounted afterwards."""
    if not Path(image).is_file():
        raise FileNotFoundError(f"The disc image '{image}' does not exist.")
    out = _powershell(
        "$ErrorActionPreference = 'Stop'; $i = Get-DiskImage -ImagePath $env:HG_ISO; $m = 0; "
        "if (-not $i.Attached) { $i = Mount-DiskImage -ImagePath $env:HG_ISO -PassThru; $m = 1 }; "
        "$d = @($i | Get-Volume | Where-Object DriveLetter | ForEach-Object DriveLetter)[0]; \"$m $d\"",
        image,
    )
    mounted, _, letter = out.rpartition("\n")[2].partition(" ")
    if len(letter.strip()) != 1:
        if mounted == "1":
            dismount_image(image)
        raise OSError(f"Windows mounted '{image}' but gave it no drive letter.")
    return f"{letter.strip().upper()}:\\", mounted == "1"


def dismount_image(image):
    _powershell("Dismount-DiskImage -ImagePath $env:HG_ISO | Out-Null", image)


def detect_disc2():
    """The drive holding disc 2 right now, or ''."""
    for root in cd_drives():
        try:
            return str(find_disc2(root))
        except (FileNotFoundError, OSError):
            pass
    return ""


# ----------------------------------------------------------------------------------------- the drive
class CdromDrive:
    """A CD/DVD drive opened for raw reads: `with CdromDrive('D:\\') as drive`."""

    def __init__(self, root):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self._kernel32
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        k.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        ]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        letter = str(root).strip()[:1].upper()
        # GENERIC_READ, share read+write, OPEN_EXISTING
        handle = k.CreateFileW(f"\\\\.\\{letter}:", 0x80000000, 3, None, 3, 0, None)
        if handle in (None, wintypes.HANDLE(-1).value):
            code = ctypes.get_last_error()
            raise RipError(
                f"Windows would not let Setup open drive {letter}: to read the audio tracks (error {code}). "
                "Rip the tracks with another program instead and choose the folder of ripped tracks."
            )
        self._handle = handle

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def _ioctl(self, code, data, out_size):
        from ctypes import wintypes

        ctypes = self._ctypes
        out = ctypes.create_string_buffer(out_size)
        returned = wintypes.DWORD(0)
        ok = self._kernel32.DeviceIoControl(
            self._handle, code, data, len(data) if data else 0, out, out_size, ctypes.byref(returned), None
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), f"DeviceIoControl {code:#x} failed")
        return out.raw[: returned.value]

    def read_toc(self):
        return self._ioctl(IOCTL_CDROM_READ_TOC, None, 4 + 8 * 100)

    def read_audio(self, lba, count):
        """`count` raw CD-DA sectors from `lba` (offsets are in 2048-byte units whatever the sector type)."""
        request = struct.pack("<qII", lba * 2048, count, CDDA)
        return self._ioctl(IOCTL_CDROM_RAW_READ, request, count * SECTOR_BYTES)


# ----------------------------------------------------------------------------------------- the TOC
def parse_toc(data):
    """[(track number, is audio, start LBA)] in disc order, the lead-out last (number 0xAA)."""
    if len(data) < 4:
        raise RipError("The drive returned no table of contents. Is the disc in the drive?")
    length = int.from_bytes(data[:2], "big")
    entries = []
    for offset in range(4, min(len(data), length + 2) - 7, 8):
        control = data[offset + 1] & 0x0F           # low nibble = Control (bit 2 set: data), high nibble = Adr
        number = data[offset + 2]
        minutes, seconds, frames = data[offset + 5 : offset + 8]
        lba = (minutes * 60 + seconds) * SECTORS_PER_SECOND + frames - PRE_GAP
        entries.append((number, not control & 4 and number != LEAD_OUT, lba))
    return entries


def audio_tracks(entries):
    """[(track number, first LBA, end LBA)] for the audio tracks; the end is the first sector not to read."""
    tracks = []
    for index, (number, is_audio, start) in enumerate(entries[:-1]):
        if not is_audio or number == LEAD_OUT:
            continue
        following_number, following_audio, following_start = entries[index + 1]
        end = following_start
        if not following_audio and following_number != LEAD_OUT:
            end -= EXTRA_GAP
        if end > start:
            tracks.append((number, start, end))
    return tracks


# ----------------------------------------------------------------------------------------- ripping
def track_file_name(number):
    return f"TRACK{number:02d}.WAV"


def rip_track(drive, start, end, path, progress=None):
    """Write sectors [start, end) of an audio track as a CD-quality WAV. Returns the number of unreadable sectors
    (replaced by silence). Raises RipError when the drive cannot read audio at all."""
    bad = 0
    lba = start
    total = end - start
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(44100)
        while lba < end:
            count = min(SECTORS_PER_READ, end - lba)
            try:
                data = drive.read_audio(lba, count)
                if len(data) != count * SECTOR_BYTES:
                    raise OSError(0, "short read")
            except OSError as exc:
                if lba == start and bad == 0 and total > SECTORS_PER_READ and not _readable(drive, lba):
                    raise RipError(
                        "The drive would not read the audio tracks (error "
                        f"{exc.errno or 'unknown'}). Rip them with another program instead and choose the "
                        "folder of ripped tracks."
                    ) from exc
                data = b""
                for sector in range(lba, lba + count):                  # one by one: keep the good ones
                    chunk = b""
                    for _attempt in range(3):
                        try:
                            chunk = drive.read_audio(sector, 1)
                            if len(chunk) == SECTOR_BYTES:
                                break
                        except OSError:
                            chunk = b""
                    if len(chunk) != SECTOR_BYTES:
                        chunk = b"\0" * SECTOR_BYTES
                        bad += 1
                    data += chunk
            out.writeframes(data)
            lba += count
            if progress:
                progress((lba - start) / total)
    return bad


def _readable(drive, lba):
    try:
        return len(drive.read_audio(lba, 1)) == SECTOR_BYTES
    except OSError:
        return False


def rip_audio(root, destination, progress=None, opener=CdromDrive):
    """Rip every audio track of the disc in drive `root` to `destination`\\TRACKnn.WAV.

    `progress(message)` gets a line per track. Returns [(track number, path, unreadable sectors)]."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    say = progress or (lambda message: None)
    ripped = []
    with opener(root) as drive:
        try:
            tracks = audio_tracks(parse_toc(drive.read_toc()))
        except OSError as exc:
            raise RipError(f"Could not read the disc's table of contents ({exc}). Is disc 2 in the drive?") from exc
        if not tracks:
            raise RipError("That disc has no audio tracks. The soundtrack is on Heavy Gear disc 2.")
        needed = sum(end - start for _n, start, end in tracks) * SECTOR_BYTES
        try:
            import shutil

            free = shutil.disk_usage(destination).free
        except OSError:
            free = needed
        if free < needed + (50 << 20):
            raise RipError(
                f"Not enough free space for the music: it needs about {needed >> 20} MB in {destination}."
            )
        say(f"Ripping {len(tracks)} audio track(s), about {needed >> 20} MB...")
        for number, start, end in tracks:
            path = destination / track_file_name(number)
            seconds = (end - start) // SECTORS_PER_SECOND
            say(f"  Track {number}: {seconds // 60}:{seconds % 60:02d}")
            bad = rip_track(drive, start, end, path)
            if bad:
                say(f"    {bad} sector(s) could not be read and were replaced by silence.")
            ripped.append((number, str(path), bad))
    return ripped
