# cdaudio

`hgcd.dll`: plays Heavy Gear's soundtrack from files, so disc 2 does not have to be in the drive.

The game plays its music through the MCI `cdaudio` device (`mciSendCommandA`) and sets the volume
through the aux API, both in `WINMM.dll`. `hgfix.py --fix music` changes the name of `HGSIM.DLL`'s
`WINMM.dll` import to `hgcd.dll`. This proxy answers the CD-audio and aux calls itself and forwards
every other `WINMM` export (timers, joystick, `mmio`) to the real one.

## What it plays

`MUSIC\TRACKnn.wav` (also `.mp3`, `.wma`, `.m4a`, `.flac`, `.ogg`, as far as Windows can decode them)
in the folder of `hgcd.dll`, where `nn` is the **track number on the original disc**. A ripper that
numbers the audio tracks of a mixed-mode disc from 02 (data on track 1) gives the right names; one that
starts again at 01 does not, so rename them. A `TRACKn` name without the leading zero is accepted too.

With no such file the proxy changes nothing: every call goes to the real `WINMM`, so a real disc works.

How the game uses the "CD" (see `docs/NOTES.md`): it counts the tracks, asks for each track's start, then plays
from one start to the next, polls the mode (stopped, playing, paused) to loop or move on, and reads the
current track. The proxy keeps a play range of tracks, plays one file at a time through the real MCI
(`mpegvideo`, which also decodes WAV), starts the next file of the range when one ends, and maps the
volume (the larger of left and right) to the file's `setaudio volume`.

It also needs the `nodisc` fix: the game first checks that a disc is in the drive.

## Working folder

When `VIDEO\B51MOVIE.AVI` sits beside the DLL, `timeGetTime` also checks (at most every 200 ms) that the working folder
is still the game folder and puts it back if not, because the `nodisc` fix finds the movies through a relative path.
In testing the folder never moved, so this is only a safety net; it runs in the sim, the only DLL that loads the proxy.

## Build

`./build.sh` (needs `clang`, `lld-link` and `llvm-dlltool`, no Windows SDK; the same as the other proxies).
CI builds it as `heavygear-cdaudio-proxy` and attaches it to releases. The DLL is never committed.

## Test

`./test.sh` builds `selftest.exe`, makes two short test tones and plays them through the DLL the way the
game would (it makes sound, for about eight seconds). It checks the device search, open, track starts, play
range, pause/resume/stop, end-of-track detection and volume, and prints the proxy's own log.

## Debug

Create an empty `hgcd.log` next to `hgcd.dll`: every emulated call is written to it, with its result.
`HGCD_MUSIC=<folder>` makes the proxy look for the track files there instead of in `MUSIC`.
