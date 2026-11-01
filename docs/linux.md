# Heavy Gear on Linux (Wine)

## Recommended: the Heavy Gear app

The Releases page has one one-file program, `HeavyGear-linux-x86_64` (no Python needed; built on
Ubuntu 22.04, so it runs on Ubuntu 22.04+, Debian 12+, Fedora, Arch / CachyOS and similar). It
installs and updates the game and is also the everyday launcher. Its pages:

* **Install & update** creates the Wine prefix, installs the game from your discs, runs the official
  1.1 / 1.2 patchers (after backing up the prefix), applies the community fixes, and installs the
  Direct3D 9 renderer and the 3Dfx (Glide) support.
* **Play** sets the frame rate, the renderer and its resolution, and gamescope scaling or a Wine
  window, then **Apply & Play**, **Play without changes** or **Stop game**.
* **Fixes** lists the community fixes that apply under Wine, each ticked at its default.
* **Tools** backs up and restores the prefix and adds the app to your applications menu.

The app opens on **Play** when it finds the game (in the prefix you used last, or
`~/Games/HeavyGear/prefix`) and on **Install & update** otherwise.

Make it executable (`chmod +x HeavyGear-linux-x86_64`) and run it. It needs Wine and `zstd` from
your distribution; `gamescope` (full screen), `unshield` (cutscene codec) and the GStreamer plugins
are recommended. The Install page shows the install command for anything missing. The app runs the
scripts in `linux/` and shows their output under **Show details**.

From a checkout instead, install Tk (`sudo pacman -S tk`, `sudo apt install python3-tk`,
`sudo dnf install python3-tkinter`) and run `linux/heavygear` (or `python3 app/heavygear.py`).
There the Direct3D 9 renderer and 3Dfx proxy are built on the spot, which needs `clang`, `lld` and
`llvm`.

The app remembers its choices in `~/.config/HeavyGearFixes/launcher.json`; choices saved by the
earlier Setup and Launcher apps carry over. A menu entry made by the earlier Launcher no longer
starts anything: **Add to applications menu** on the Tools page replaces it. For 3Dfx, point the
Install page at a folder with `dgVoodoo2_79_*.zip` and `dxvk-*.tar.gz` (see below) or at a
`glide2x.dll`. Patch files and discs are never bundled.

## Script setup (advanced)

Copy your two discs into the repository folder first, as `HG-DISC-1/` and `HG-DISC-2/` (see the
[main README](../README.md)). Then, from the repository folder:

```bash
linux/setup-heavygear-wine.sh                                  # one time; makes ~/Games/HeavyGear/prefix
python3 patcher/hgfix.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear   # speed and display fixes
linux/run-heavygear.sh                                         # play
```

**Packages.** You need Wine and `unshield`; `gamescope` and the GStreamer plugins are recommended.
Tested on CachyOS (Arch). Commands for other distributions are in `linux/distro.sh`
(the scripts print the right one for yours when something is missing):

| | Arch / CachyOS | Debian / Ubuntu | Fedora |
|---|---|---|---|
| Wine | `wine` | `wine wine32:i386` (after `dpkg --add-architecture i386`) | `wine` |
| codec extraction | `unshield` | `unshield` | `unshield` |
| full-screen scaling | `gamescope` | `gamescope` (newer releases) | `gamescope` |
| video | `gst-plugins-base gst-plugins-good gst-libav` (+ `lib32-` versions) | `gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav` | `gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugin-libav` |

**The fixes.** `patcher/hgfix.py` is safe to re-run; `--list` shows which fixes it applies,
`--skip NAME` / `--fix NAME` change that, and `--restore` puts the original files back.

* **Full screen:** the launcher runs the game inside **gamescope**, which scales its 640×480
  screen up to fill the monitor. Without gamescope, Wine draws it 1:1 in the top-left corner.
  Options: `HG_SCALE=fit` (fill height, smoother), `HG_WINDOW=1280x960` (gamescope in a window of
  that size instead of full screen) or `HG_GAMESCOPE=0` (plain Wine).
* **Direct3D 9 renderer at a higher resolution:** with an `hgd3d9.res` in the game folder (for example
  `1440x1080`), the launcher makes that gamescope's game size and runs the game without a Wine
  virtual desktop, with Wine's emulated display modes (`EmulateModeset`, set for `HG.EXE` only).
  The 640×480 menus and movies are scaled up to fill the screen and missions render at the full
  size; it switches back and forth by itself. This needs the `display` and `moviebg` fixes (both
  on by default under Wine). Without `hgd3d9.res` everything stays at 640×480 as before.
  The launcher sets or removes that registry value on every start, so it follows the file.
  `HG_RES=640x480` turns the mode off for one run.
* **Borderless full screen (official 1.2, on by default for 1.2):** `hgfix.py GAME --fix borderless` (or the app's
  *Borderless full screen* box) makes the game draw menus and movies in one borderless window the size of the
  desktop, scaled to the largest 4:3 area with black bars, with no display-mode switches. The launcher sees the
  patched `HGSHELL.DLL` and starts the game straight in Wine: no gamescope, no emulated display modes, and no
  virtual desktop unless `HG_DESKTOP` asks for one. Missions with the Direct3D 9 renderer use the same window:
  without `hgd3d9.res` they render at the 4:3 area's size; with it, at that size scaled into the area. It replaces
  the `display` and `moviebg` fixes. Software-renderer missions draw through the same window; with DX5DRAW
  selected the launcher turns on Wine's emulated display modes so its 640x480 missions are scaled too. With the 3Dfx
  renderer under nGlide it tells nGlide to render at the desktop's resolution in 4:3 (`NGLIDE_RESOLUTION=1`,
  `NGLIDE_ASPECT=1`; set either yourself to override); under dgVoodoo2 it uses the emulated display modes
  (not tested). The launcher also removes any Windows version set for `HG.EXE` in Wine (older
  setups set Windows 98, which breaks the scaled movies), on every start and with or without this fix.
* **Music:** the soundtrack is CD audio on the real disc 2, which a file copy can't hold. Put
  disc 2 in your drive before launching: the launcher detects it and makes it drive D:.
  Without it you'll get *"Cannot acquire audio CD device"* at mission start. Click OK and the
  mission still runs, without music.
* **Too fast:** the menus and the mission loop advance their animations once per frame with no
  timing, so on a modern PC they race. `patcher/hgfix.py` patches `HGSHELL.DLL` and
  `HGSIM.DLL` in the game folder with a real frame limiter, and keeps `.orig` backups:
  `python3 patcher/hgfix.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear --menu-fps 30 --sim-fps 30`
  Re-run it with other numbers to tune, or with `--restore` to undo. Works on v1.0 and v1.2. [NOTES.md](NOTES.md) has the details.
* **Controls:** a WASD + mouse layout is in `mods/wasd/` (key table in its README). Install with
  `python3 patcher/hg_controls.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear wasd`, or go back
  with `... original`.
* **Logs:** Wine's messages go to `~/Games/HeavyGear/heavygear.log`. For video problems run
  with `HG_DEBUG=video`.

The setup script:

* builds its own Wine prefix, so your `~/.wine` is untouched
* copies the game from disc 1 (`INSTALL/DATA`, which is already a complete install) to `C:\HeavyGear`,
  plus the control-scheme files the original installer adds (`--controls sim` for the Sim scheme)
* maps `HG-DISC-2` as CD-ROM drive `D:`. The game won't start without it: it looks for
  `\video\B51MOVIE.AVI` on the **first** CD-ROM drive it finds.
* installs the Indeo 5 codec (`ir50_32.dll`, extracted from disc 1's own installer cab with
  `unshield`) so the cutscenes play, plus the game's two fonts
* tells Wine to report Windows 98 to `HG.EXE`

**Renderers.** You choose the renderer in the game's options screen (or on the app's Play page), and
the game saves the choice to `dllfile.ini`. The app installs and selects the Direct3D 9 renderer; if a
renderer gives trouble, **software** is the most reliable fallback under Wine. The options are:

| Plugin | API | Under Wine |
|---|---|---|
| `3dfx_hgd3d9.dll` | Direct3D 9: this repository's replacement renderer (`renderer/hgd3d9`, options in its `OPTIONS.md`); needs v1.2 | works with Wine's own Direct3D 9; keep DXVK's `d3d9.dll` out of the game folder |
| `RENDDRAW.DLL` / `I76DRAW.DLL` | software rasterisers (the game shows the result via DirectDraw); I76DRAW is the older Interstate '76 one | should just work |
| `DX5DRAW.DLL` | Direct3D 5 | try Wine's built-in; better with dgVoodoo2 (below) |
| `3DFXGEAR.DLL` | 3Dfx Glide 2 | via dgVoodoo2 + DXVK (`linux/setup-glide.sh`) |

**3Dfx (Voodoo / Glide) renderer.** The game's Glide plugin needs a Glide wrapper, plus our small proxy that
fixes the black squares on smoke, dust and fire. `linux/setup-glide.sh` installs both into the game folder only:
`glide2x.dll` is our proxy (built on the spot from `tools/glidelog`) and `glide2x_real.dll` is the wrapper.
Building the proxy needs `clang`, `lld`, `llvm` and `python3`; the script prints the install command if they're missing.

The wrapper is chosen in this order:

1. a `glide2x_real.dll` already in the game folder (it is kept as it is);
2. `HG_GLIDE_DRIVER=/path/to/glide2x.dll`, for example nGlide 2.10 (zeus-software.com; install it with
   `WINEPREFIX=~/Games/HeavyGear/prefix wine nGlide210_setup.exe /S`, then point `HG_GLIDE_DRIVER` at the
   `glide2x.dll` it leaves in the prefix's `syswow64` folder);
3. a `Glide2x.dll` already in the game folder from an earlier install (it becomes `glide2x_real.dll`);
4. **dgVoodoo2 2.79.x** + **DXVK**: put `dgVoodoo2_79_*.zip` (dege.freeweb.hu; newer 2.8x releases crash under
   Wine, WineHQ bug 58731) and `dxvk-*.tar.gz` (github.com/doitsujin/dxvk/releases) in `wrappers/`. The script then also
   installs DXVK's 32-bit `d3d11.dll`/`dxgi.dll`, and `run-heavygear.sh` loads them for the game.
   Settings: `C:\HeavyGear\dgVoodoo.conf`.

`setup-glide.sh --remove` moves all of it aside (to `C:\HeavyGear\_glide_removed`); `--no-fix` installs without the particle fix.
Then pick **3Dfx** in the options screen. A file named `glidelog.txt` in the game folder switches on call logging
(tens of MB per mission), so delete it for normal play. How the fix works: [NOTES.md](NOTES.md) and `tools/glidelog/README.md`.

**Troubleshooting**

* *"fatal error #11: SYSERR_NOPREFS … Can't open input mapping file"*: `INPUTW.MAP` is missing
  from `C:\HeavyGear`. Re-run the setup script, or copy the files from `C:\HeavyGear\ACTION`.
* *"Please insert Heavy Gear CD 2"*: check that `~/Games/HeavyGear/prefix/dosdevices/d:`
  points to `HG-DISC-2`, and that `winecfg` → Drives shows D: as CD-ROM.
* *A warning about 256-colour mode*: answer **No**. It's advice from 1997, not an error.
* *Videos are black or skipped*: run with `HG_DEBUG=1` and look for `ir50`/`IV50` errors.
  Installing `gst-libav` may also give Wine's own decoders a way to handle Indeo 5.
* *Need more logging*: in `C:\HeavyGear\HG.INI`, `[Debug]` section, set `ToNull=0`,
  `ToLog=1`, `All=1`. The engine then writes `kra.log`.
* *Patches*: see "Official patches 1.1 / 1.2" below.

**Official patches 1.1 / 1.2**

Get Activision's patch files `hgp187d.exe` (1.1) and `HGPATC12.EXE` (1.2) (they're not included
here; old-game archive sites carry them) and put them in `patches/hgp187d/` and `patches/hgpatc12/`.
Back up your prefix first (`linux/backup.sh 1.0`; `linux/restore.sh 1.0` puts it back), then run `linux/apply-patches.sh`. It
puts the exact 1.0 DLLs back (the patches are RTPatch delta patches and only apply to byte-exact
files), writes the registry keys the original installer would have (`HKLM\Software\Activision\Heavy
Gear` with `EXE`/`FTP` values and a version subkey, plus `App Paths\HG.EXE`), runs each patcher, and
fixes the lowercase file names they leave behind. Afterwards re-apply the speed/display fix:
`python3 patcher/hgfix.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear` (it detects v1.0 or v1.2).
1.2's new textures are in `C:\HeavyGear\patch\`; most of its visual additions are for the 3D
renderers (D3D / 3Dfx).
