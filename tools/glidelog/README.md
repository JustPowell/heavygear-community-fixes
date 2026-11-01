# glidelog

A proxy `glide2x.dll` for the 3Dfx path. It fixes the black squares on particle effects (smoke, dust, fire)
and can log every Glide call.

## The particle fix

The game draws particles as colour-keyed P_8 textures. Their transparency is stored in the top byte of the
palette entries (0xFF = transparent, lower = more opaque) and the chroma-key colour does not match the
background, so the driver draws the background as black squares. The proxy converts each keyed texture to
AP_88 (8-bit alpha plus palette index), with alpha = 255 - top byte and the key colour transparent, keeps the
result in the top 128 KB of texture memory (the game leaves it free) and turns the chroma key off.
The stepped contours left in the smoke come from the original palette art, not from this conversion.

Most particles are not keyed, though: the game draws them with the key off and blends them by the texture's
alpha, which a P_8 texture does not have. The proxy converts those textures the same way, without a key colour.
(Until 2026-10-31 it handled only the keyed ones, and most smoke stayed black until an alt-tab, after which the
game uploads its particles with alpha itself.)

Tested with nGlide 2019 under Wine and nGlide 2.10 on Windows 11. The fix is on by default. To switch it off, put the word `nofix` in
`glidefix.cfg` next to the DLL.

## Install

Put the proxy in the game folder as `glide2x.dll` and the real driver next to it as `glide2x_real.dll`.
Delete any old `glidefix.cfg`. The compiled DLL is not in this repo: build it (below) or take `glide2x.dll` from a release.

## Logging

Off unless a file named `glidelog.txt` already exists in the game folder (create an empty one to turn it on;
a mission writes tens of MB). The attach line says whether the fix is on.

## Build

`./build.sh` needs clang, lld-link and llvm-dlltool. `exports.txt` lists the Glide 2 exports to wrap
(`gen.py` generates `glidelog.c` and `glide2x.def`).
