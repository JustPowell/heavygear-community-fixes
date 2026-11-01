# Heavy Gear (1997) community fixes

Fixes and installers for playing Activision's *Heavy Gear* (1997, Windows 95) on modern systems:
Linux under Wine, and Windows 10 / 11.

> **You need your own copy of the game.** This repository contains no game files: no disc
> contents, patches or game code. The fixes patch your installed copy on your own machine and keep
> backups of what they change. Not affiliated with or endorsed by Activision.

| | Status |
|---|---|
| Linux (Wine) | the Heavy Gear app; tested on CachyOS, other distributions should work ([docs/linux.md](docs/linux.md)) |
| Windows 10 / 11 | the Heavy Gear app; tested on one Windows 11 machine, reports welcome ([docs/windows.md](docs/windows.md)) |

## Two ways to use it

**1. Install everything from your discs.** The Heavy Gear app (`HeavyGearFixes.exe` or
`HeavyGear-linux-x86_64` from the Releases page, or `linux/heavygear` / `python app\heavygear.py` from
a checkout) installs the game from your discs or from copies of them (on Windows also from `.iso` or
`.mds`/`.mdf` images of your discs), runs the official 1.1 and 1.2
patchers, applies the fixes below and installs the Direct3D 9 renderer. Afterwards it is the launcher
too: fixes, renderer, frame rate, play. The official patch files (`hgp187d.exe` for 1.1,
`HGPATC12.EXE` for 1.2) are not included: download them yourself and point the app at them, or put
them in `patches/hgp187d/` and `patches/hgpatc12/` in this folder.

**2. Patch a game you have already installed.** If you installed the game and the 1.1 and 1.2
patches yourself, run the fixes against the game folder (Python 3, any OS):

```bash
python3 patcher/hgfix.py "PATH/TO/HeavyGear" --list    # what it would change
python3 patcher/hgfix.py "PATH/TO/HeavyGear"           # apply (backups are kept)
python3 patcher/hgfix.py "PATH/TO/HeavyGear" --restore # undo
```

Or point the app at that folder: it applies the same fixes and also picks the renderer and frame rate.
The platform guides cover both routes in detail: [docs/linux.md](docs/linux.md),
[docs/windows.md](docs/windows.md).

## What the fixes do

`patcher/hgfix.py` patches the game's own DLLs (v1.0 from the disc or v1.2 from the official
patch; anything else is refused unchanged). `--list` shows which fixes apply on your platform,
`--fix NAME` / `--skip NAME` change that, `--restore` puts the originals back.

| Fix | Problem it solves | Default on |
|---|---|---|
| `limiter` | menus and missions run far too fast on modern PCs | Linux, Windows |
| `display` | black / half-drawn debrief screen after a mission; black intro movie | Linux (Wine) |
| `anet2` | v1.2 freezes on a black screen when a mission starts | Linux, Windows |
| `moviebg` | with the Direct3D 9 renderer at a higher resolution (`hgd3d9.res`), movies play behind a black window | Linux (Wine) |
| `movie32` | Windows: the game crashes now and then around a movie (after the intro, a briefing, or the movie after a mission) | Windows (not with `borderless`, which replaces it) |
| `dx5draw` | Windows: menus turn red after a mission. Sets the game's own Direct3D plugin (`DX5DRAW.DLL`) aside, so that renderer is no longer offered | Windows |
| `partdepth` | v1.2: particle sprites have no depth, so far dust and smoke show through hills (renderers with a depth buffer) | Linux, Windows (v1.2 only) |
| `nodisc` | play without disc 2 in the drive: cutscenes come from a `VIDEO` folder in the game folder | off (opt-in) |
| `music` | soundtrack from ripped track files instead of the CD (turns on `nodisc`; needs `hgcd.dll` from `tools/cdaudio`) | off (opt-in) |
| `borderless` | v1.2: the game runs in one borderless full-screen window; menus, movies and missions are scaled into the largest 4:3 area with black bars, with no display-mode switches (safe alt-tab, no gamescope). Replaces `display`, `moviebg` and `movie32`. Software missions stay 640x480, scaled | Linux, Windows (v1.2 only) |
| `palette` | experimental: re-sends the menu palette once; did not cure the red menus (see `dx5draw`). Still accepted, not offered by the app | off (opt-in) |
| 3Dfx particles (not an `hgfix` fix) | 3Dfx renderer: smoke, dust and fire drawn as black squares. Fixed by a proxy driver built from `tools/glidelog` and installed by `linux/setup-glide.sh` (needs clang, lld, llvm) | Linux (script), Windows (manual). The old `hgfix.py --fix glide` is retired |

Also: a WASD + mouse control layout (`patcher/hg_controls.py`, `mods/wasd/`, with a printable card, `mods/wasd/wasd-controls.pdf`), a disc-free music
proxy (`tools/cdaudio`) and a replacement Direct3D 9 renderer (`renderer/hgd3d9`).

## Layout

```
app/         the Heavy Gear app (install, fixes, renderer, play) for Linux and Windows
patcher/     hgfix.py (the fixes) and hg_controls.py (WASD layout), any OS
linux/       the Wine setup, launcher, backup/restore, official-patch and 3Dfx scripts the app runs, and its Linux build
windows/     the app's Windows installer code, advanced setup scripts, renderer build/install, and .exe build scripts
renderer/    hgd3d9, the Direct3D 9 renderer plugin
tools/       glidelog (3Dfx particle-fix proxy) and cdaudio (music without the disc)
mods/        control layouts (stored as edits to the game's own files)
docs/        linux.md, windows.md, NOTES.md (technical notes), research/ (the renderer plugin API, the shell display)
AGENTS.md    rules and checks for AI coding agents (and people) working on this repository
```

## Your game files

For the script setup, copy your two discs into this folder; they are git-ignored:

```
HG-DISC-1/   contents of disc 1 (has INSTALL/DATA/HG.EXE)
HG-DISC-2/   contents of disc 2 (has VIDEO/B51MOVIE.AVI)
```

Never commit game files, patches or anything made from them. CI fails on any binary file except
the WASD card (`mods/wasd/wasd-controls.pdf`).

## AI usage

Much of the code, tests and documentation here was written with AI coding assistants, mainly
Anthropic's Claude through Claude Code, working under the maintainer's direction. The maintainer
decides what is built and tries the changes in the game; the automated tests run on every push.
Even so, AI-written code can be wrong in ways that look right, and testing so far covers two
machines (one Linux, one Windows 11). Keep the backups the tools make, and please report anything
that misbehaves.

The research notes on how the game works come from studying the maintainer's own copy of the game,
and describe its behaviour in our own words. No game files, patches or decompiled code are included;
the WASD layout is stored as edits to the game's own control files, applied to your copy. Contributions
made with AI help are welcome on the same terms: say so in the pull request, and see
[AGENTS.md](AGENTS.md).
