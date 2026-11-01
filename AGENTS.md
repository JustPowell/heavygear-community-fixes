# AGENTS.md

Instructions for AI coding agents (Claude Code, Copilot, Codex, local models, ...) working in this repository.
Human contributors: the same rules apply to you.

Fixes, installers and tools for Activision's *Heavy Gear* (1997), played under Wine on Linux and on Windows 10/11.
This repository is exported from the maintainer's development repo (see `.public-export`); pull requests are
welcome and are carried over there by hand.

## Hard rules

1. **No game material, ever.** Never add game files, disc contents, official patches, decompiled or disassembled
   game code, game bytes, compiled DLLs, or third-party wrappers (dgVoodoo2, nGlide, DXVK) to a tracked file, and
   never paste them into an issue or pull request. Describe game behaviour, addresses and field layouts in your own
   words only.
2. **No binary files.** CI fails on any binary file except the WASD card `mods/wasd/wasd-controls.pdf`.
3. **The player's game files are read-only to you.** `HG-DISC-1/`, `HG-DISC-2/`, `patches/` and any installed game
   folder may be read by tools, never changed or deleted. The fixes change an installed game only through
   `patcher/hgfix.py`, which keeps backups.
4. **Don't commit, push or merge unless asked**, and leave changes you did not make alone.
5. A new renderer is installed as an extra `PLUGIN\*.dll`; never overwrite one of the game's own plugins.
6. Keep changes small and inside the task. Ask before adding dependencies or files the task did not name. A new or
   changed fix also needs its entry in `OFFERED`/`LABELS` in `app/backend.py`.

## Check your work (what CI runs)

```bash
python3 -m py_compile app/*.py patcher/*.py windows/*.py linux/*.py tools/glidelog/gen.py
python3 -m unittest discover -s windows -p "test_*.py"
python3 -m unittest discover -s linux -p "test_*.py"
xvfb-run -a python3 -m unittest discover -s app -p "test_*.py"     # the window tests need a display
xvfb-run -a python3 app/heavygear.py --self-test                   # builds every page over both back ends
for f in linux/*.sh tools/glidelog/build.sh tools/cdaudio/*.sh renderer/hgd3d9/*.sh; do bash -n "$f"; done
python3 patcher/hgfix.py . --list && python3 patcher/hgfix.py . --list --platform windows
```

CI also runs the Windows and app tests on Windows. Run the checks before saying a task is done and report failures
as they are; if you changed Windows-only behaviour and could not run it on Windows, say so. Some Windows installer
tests refuse to run while `HG.EXE` is running.

## Layout

- `patcher/hgfix.py`: the fixes, as named byte patches to the game's DLLs (v1.0 or v1.2 only; anything else is
  refused unchanged). `patcher/hg_controls.py`: the WASD layout.
- `app/`: the one Tk app for both platforms: `heavygear.py` (entry), `ui.py` (window), `backend.py` (shared logic and
  the offered fixes), `backend_linux.py`, `backend_windows.py`.
- `linux/`, `windows/`: the setup cores and scripts the back ends wrap (`windows/installer_core.py`,
  `windows/disc2_media.py`, `windows/disc_image.py`, `linux/setup_core.py`, ...).
- `renderer/hgd3d9/`: the Direct3D 9 renderer plugin (C, clang + lld). `tools/glidelog/`: the 3Dfx particle-fix
  proxy. `tools/cdaudio/`: music without the disc.
- `docs/linux.md`, `docs/windows.md`: the player guides. `docs/NOTES.md` and `docs/research/*.md`: what is known
  about the game's internals. Read the relevant note before changing behaviour, and add new findings to it.

## Style

Match the file you are editing: its comment density, naming and idioms. Tests use `unittest`. Comments say why,
in plain words.

## AI use

Much of this repository was written with AI coding assistants; see "AI usage" in `README.md`. If you are an agent,
say so in your pull request, and say what you tested and how.
