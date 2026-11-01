# Heavy Gear on Windows 10 / 11

> **Status: tested on one machine.** Most of this repository was developed under Wine on Linux. The
> Heavy Gear app, the fixes (including borderless full screen) and the Direct3D 9 and 3Dfx (nGlide)
> renderers have been tried on one Windows 11 PC; other hardware and Windows 10 are untried. Reports
> (working or not) are very welcome as GitHub issues.

## Recommended: the Heavy Gear app

The [Releases page](https://github.com/JustPowell/heavygear-community-fixes/releases/latest) has one one-file program, `HeavyGearFixes.exe`. It needs no Python, PowerShell,
PyInstaller, LLVM or Windows SDK, and bundles the community patcher, the WASD controls, the
Direct3D 9 renderer and the music proxy for playing without disc 2. It installs and updates the game
and is also the everyday launcher. It opens on **Play** when it finds the game (the folder you used
last, or a retail install Windows has registered) and on **Install & update** otherwise.

The program is not code-signed, so on first run Windows may say *"Windows protected your PC"*: click
**More info**, then **Run anyway**. Some antivirus tools also flag one-file Python programs like this one;
it is built in the open by the `windows-exe` workflow in the Actions tab.

On **Install & update**, choose the game folder at the top (the default for a new copy is
`%USERPROFILE%\Games\HeavyGear`). If the game is already there, its files are kept; otherwise browse
to your disc 1 drive or a folder copy of it. The app also finds a disc folder or official patch file
beside itself, but you don't need to put anything there. Every path field says whether it found what
it needs.

Both disc fields also take a disc image (**Image...**): a `.iso`, or an Alcohol 120% `.mds`/`.mdf`
pair (choose either file; both must be in the same folder). `HG-DISC-1.iso`/`.mds` or
`HG-DISC-2.iso`/`.mds` beside the app is found by itself. **Install / Update** mounts the image with
Windows' own image support (no administrator approval) and dismounts it when it is done; an `.iso`
that was already mounted is left mounted. An `.mds`/`.mdf` is first turned into a temporary `.iso`
of its data track (deleted afterwards). A disc 2 `.iso` has the cutscenes but not the music, since
an `.iso` holds only data; an `.mds`/`.mdf` keeps the CD-audio tracks, and **Rip the music** reads
them from it.

Official 1.1/1.2 patches are optional and are not bundled. Select patch files you already have
with **Browse...**; the app requests administrator approval when it runs the legacy official
patchers. Before patching, it backs up `HG.EXE`, `HGSHELL.DLL`, and `HGSIM.DLL` under
`%LOCALAPPDATA%\HeavyGearFixes\backups`. Its own fixes and renderer are included. The Direct3D 9
renderer can be installed after official 1.2, or for an existing 1.2 installation.

Optional cutscene support installs Indeo 5 and the game fonts from your disc after administrator
approval. If Windows does not already have Indeo and `unshield` is on `PATH`, the app extracts the
codec from disc 1's installer cabinet; otherwise select an extracted `ir50_32.dll`.

The app copies files from disc 1 without running the original 16-bit installer. The
**Play without disc 2** section removes the need for disc 2 when playing: put disc 2 in the
drive (**Find disc** picks it), tick **Copy the cutscenes** and **Rip the music**, and the app copies the
`VIDEO` folder into the game folder and reads the disc's audio tracks to `MUSIC\TRACKnn.WAV` (about
360 MB; a few minutes), then applies the matching fixes. If you already have the tracks ripped with another
program, choose their folder instead. Without these options the game still needs disc 2 in the first
CD/DVD drive when played, and music requires the disc's CD audio. Details and the command-line
equivalent: [Playing without a disc](#playing-without-a-disc).

The **Fixes** page lists the community fixes that apply on Windows, each ticked at its default, and
the **Play** page sets the frame rates, the renderer and its resolution (see [Play page](#play-page)).
The app remembers its choices in `%LOCALAPPDATA%\HeavyGearFixes\launcher.json`; choices saved by the
earlier Setup and Launcher apps carry over.

## Script-based setup (advanced)

To set up with the PowerShell scripts instead of the app, run:

```powershell
.\windows\setup-heavygear.ps1
```

By default it installs the `ACTION` controls into `%USERPROFILE%\Games\HeavyGear`. The disc 1
files must be in the repository's `HG-DISC-1` folder. To use a mounted disc or a different folder,
pass `-Disc1Path` and/or `-GamePath`. Choose `-Controls sim` on the first install for the
simulator controls. The script copies `INSTALL\DATA` (a complete game install) and the chosen
control files into the game folder; existing files are preserved on re-runs. `INPUTW.MAP` is
required or missions fail with *SYSERR_NOPREFS*.

Choose `-Controls wasd` to copy the Action base layout and apply this project's WASD bindings.
This requires `dist\hg_controls.exe` or Python 3. The installer keeps the original `INPUTW.MAP`
and `GAMEKEY.MAP` as `.orig` files so the layout can be restored with
`hg_controls.exe "<game folder>" original`.
The control maps are made writable before editing; disc copies can carry read-only attributes.

To validate and reuse a game installed by the original Windows installer, pass its folder and
`-ExistingInstall`. By default, this mode does not copy disc files or change installed controls;
add `-Controls wasd` to apply the updated WASD layout:

```powershell
.\windows\setup-heavygear.ps1 -GamePath "${env:ProgramFiles(x86)}\Activision\HeavyGear" -ExistingInstall
.\windows\setup-heavygear.ps1 -GamePath "${env:ProgramFiles(x86)}\Activision\HeavyGear" -ExistingInstall -Controls wasd
```

The script does not modify the registry or Windows system files by default. Indeo 5 and the two
game fonts can be installed system-wide with an elevated PowerShell session. Install `unshield`
and make it available on `PATH`, or supply an already extracted `ir50_32.dll`:

```powershell
.\windows\setup-heavygear.ps1 -InstallSystemComponents -CodecPath C:\path\to\ir50_32.dll
```

Without `-CodecPath`, the script extracts `ir50_32.dll` from disc 1's `INSTALL\DATA1.CAB` with
`unshield`; Windows' `expand.exe` cannot extract this InstallShield cabinet. The script registers
the codec for 32-bit video playback and installs the fonts from `INSTALL`. It refuses to replace
different existing system codec/font files or registrations. Installing the codec can restore
Indeo cutscene playback; Windows already supplies the DirectShow/ActiveMovie framework.

The game needs disc 2 in the **first** CD/DVD drive letter (it looks for `\VIDEO\B51MOVIE.AVI`).
Use the real disc, or mount an image of it (double-click an `.iso` on Windows 10/11). The
soundtrack is CD audio, so music only plays from the real disc or a BIN/CUE image mounted with
a tool that supports audio tracks.

### Playing without a disc

The optional `nodisc` fix removes the need for disc 2 in the drive. The game's disc checks are changed to read
the cutscenes from a `VIDEO` folder inside the game folder instead, so copy disc 2's `VIDEO` folder there. One
command does both (the fix is off unless asked for):

    py -3 patcher\hgfix.py %USERPROFILE%\Games\HeavyGear --fix nodisc --disc2 D:\

`--disc2` takes the mounted disc, a folder copy of it, or its `VIDEO` folder; files already in the game's
`VIDEO` folder are kept. Re-run without `--fix nodisc` to turn it off again (`--restore` puts every original
file back). On its own this leaves the soundtrack out: it is CD audio, so the game shows
*"Cannot acquire audio CD device"* at mission start (click OK, the mission runs without music).

#### Music without the disc

The optional `music` fix (it turns `nodisc` on too) plays the soundtrack from files. Rip disc 2's audio tracks
to WAV (or MP3) with any CD ripper and name them by their **track number on the disc**: `TRACK02.WAV`,
`TRACK03.WAV` and so on (`Track02.wav` as most rippers write it is fine). Then:

    py -3 patcher\hgfix.py %USERPROFILE%\Games\HeavyGear --fix music --disc2 D:\ --music-from C:\rips\heavygear

`--music-from` copies the `TRACKnn` files into the game's `MUSIC` folder. The fix needs `hgcd.dll`, a small
proxy that takes the place of `WINMM.dll` for `HGSIM.DLL`: it is found in the game folder, next to `hgfix.py`
or in `tools\cdaudio` (build it with `tools/cdaudio/build.sh`, or take it from a release), or give it with
`--hgcd FILE`. The fix is refused when it cannot be found, because the game would not start without it.
The music volume setting keeps working. While `MUSIC` holds no track files the proxy passes everything to the real
`WINMM`, so a real disc still plays. If the numbering looks off (the wrong piece in a menu or mission), your
ripper probably started again at 01 instead of using the disc's track numbers: rename the files. Create an
empty `hgcd.log` next to `hgcd.dll` to see what the game asked for. Details: [tools/cdaudio/README.md](../tools/cdaudio/README.md).

### Apply the official and community patches

Place Activision's patch files in the repository's ignored `patches` folders:

* `patches\hgp187d\hgp187d.exe` (official 1.1 patch)
* `patches\hgpatc12\HGPATC12.EXE` (official 1.2 patch)

Then open PowerShell as Administrator and run from the repository folder:

```powershell
.\windows\apply-patches.ps1
```

The script backs up the game folder under `backups`, registers the selected install in the 32-bit
registry view for the old patchers, runs 1.1 and then 1.2, and applies this repository's Windows
fixes to the resulting game. It supports both the disc-copy install and an existing retail
installation; for the latter, pass its folder with `-GamePath`. The official patchers are legacy
GUI programs whose confirm and progress windows render all-black when launched detached (double-clicked
or via Start-Process, which gives them no console handle); the script runs them from a command prompt
instead, so the Proceed/Quit window renders and you click Proceed. Do not run the game as Administrator;
start it normally after the script finishes. This applies the Windows defaults listed under
[Apply the fixes from the command line](#apply-the-fixes-from-the-command-line). With disc 2 mounted in the first CD/DVD drive, start the default install with:

```powershell
$game = Join-Path $env:USERPROFILE 'Games\HeavyGear'
Start-Process -FilePath (Join-Path $game 'HG.EXE') -WorkingDirectory $game
```

To apply only one official update, use `-Version 1.1` or `-Version 1.2`. The 1.1 patch requires
the clean v1.0 files from disc 1; `-Version 1.2` is for applying 1.2 after 1.1. If the unofficial
fixes are already applied, the script first restores their `.orig` files and verifies the 1.0
originals for 1.1. For a failed or unwanted update, restore the backup folder printed by the
script.

If the 1.1 patch completed but the 1.2 patch did not, rerun only 1.2:
`.\windows\apply-patches.ps1 -Version 1.2`. The script keeps the version subkey created by 1.1;
do not reinstall to `C:\HeavyGear` just for the patcher. Its 32-bit `App Paths\HG.EXE` entry
points to the selected `-GamePath`.

If both official patches completed but the community-fix step failed (for example because Python
is missing), do not rerun the official patchers. Fix the cause, then apply just the community fixes:

```powershell
.\windows\apply-patches.ps1 -FixesOnly
```

To use a built `hgfix.exe` instead of Python, pass its path with `-HgfixPath`. The `-FixesOnly` mode does
not require elevation. Once the fixes succeed, install the renderer separately if 1.2 was already
applied:

```powershell
.\windows\install-renderer.ps1 -GamePath "$env:USERPROFILE\Games\HeavyGear" -RendererPath .\dist\3dfx_hgd3d9.dll
```

If using the Python script instead, install Python 3 from python.org; the Microsoft Store
`python` app-execution alias is not a Python interpreter.

The script also passes the community fix options through to `hgfix`. For example, to use a 25 FPS
simulation limiter, or to change which fixes are enabled by default:

```powershell
.\windows\apply-patches.ps1 -FixesOnly -SimFps 25
.\windows\apply-patches.ps1 -FixesOnly -MenuFps 30 -SimFps 25 -Skip anet2
.\windows\apply-patches.ps1 -FixesOnly -Fix display
```

`-MenuFps` and `-SimFps` default to 30. `-Fix` and `-Skip` can each be specified more than once.
## Apply the fixes from the command line

For direct command-line use, build the developer executables with `windows\build-exe.ps1`, or
install Python 3 and run the scripts directly:

```
hgfix.exe "C:\Games\HeavyGear" --list         (or: py patcher\hgfix.py "C:\Games\HeavyGear" --list)
hgfix.exe "C:\Games\HeavyGear"                 apply
hgfix.exe "C:\Games\HeavyGear" --restore       undo
```

On Windows the defaults are the frame limiter (`limiter`), the red-menu fix (`dx5draw`), the 1.2
mission-start fix (`anet2`) and the movie crash fix (`movie32`); on a 1.2 game also particle depth
(`partdepth`) and borderless full screen (`borderless`), which makes `movie32` unnecessary and drops
it. `--list` shows them for your game. The 3Dfx particle
fix is a separate proxy DLL, not part of `hgfix`: see [3Dfx particle fix](#3dfx-particle-fix-proxy-glide2xdll).
The **display** fix (black or broken debrief screen after a mission, intro movie handling) works around
Wine's DirectDraw only; `hgfix` ignores it on Windows, where DirectDraw does not have that problem.

If the menus turn red after a mission, apply the **red-menu fix**. It is on by default on Windows,
as the **Red-menu fix** box on the app's Fixes page, or `--fix dx5draw` / `--skip dx5draw` for `hgfix.exe "C:\Games\HeavyGear"`. It renames
`PLUGIN\DX5DRAW.DLL` to `DX5DRAW.DLL.off`: the shell's probe of that plugin makes Windows' 8-bit
compatibility layer lose the menu palette, and without the file the probe cannot run. The game's
own Direct3D renderer is then not offered; the other renderers (software, 3Dfx, Direct3D 9 renderer) are
unaffected. The fix is skipped, with a message, while `DLLFILE.INI` selects `DX5DRAW.DLL` as the
renderer; pick another renderer first. Applying the fixes again with it unticked, or
`hgfix.exe "C:\Games\HeavyGear" --restore`, renames the file back. The cause is written up in
[NOTES.md](NOTES.md) ("Red shell after a mission"); so far it is confirmed on one machine.

The earlier experimental `--fix palette` is not offered in the app,
because it does not address that cause; it is still accepted by `hgfix`.

WASD controls: `hg_controls.exe "C:\Games\HeavyGear" wasd` (`original` to go back).

### Play page

The app's **Play** page applies the fixes and settings and starts the game. It does not need
`hgfix.exe` beside it. Choose 30 or 60 FPS for menus and simulation; the fixes come from the
**Fixes** page, where the limiter, red-menu fix and mission-start fix are on by default on Windows,
and borderless full screen and particle depth are on by default when the installed game is the
official 1.2 (v1.0 keeps the older defaults, with the movie crash fix in place of borderless). 30 FPS
simulation is recommended; 60 FPS may cause
gameplay or timing glitches.

The renderer list contains only DLLs installed in the selected game's `PLUGIN` folder. Choosing
one writes its DLL filename to `DLLFILE.INI`; **Keep the game's current renderer setting** leaves
that file untouched. For Direct3D 9 renderer, enter a window size such as `1920x1080`, or leave it blank
to use the renderer's default. This setting is written to `hgd3d9.res` only when Direct3D 9 renderer is
selected. Existing `DLLFILE.INI` and `hgd3d9.res` files are backed up once as
`*.hglauncher.bak` before they are changed or removed.

**Apply & Play** applies the selected fixes and settings before starting `HG.EXE`. **Play without
changes** starts the game without patching files or changing renderer/resolution settings. If the
game is installed under Program Files, the app requests administrator approval if Windows denies access to game files.

## Renderers

Choose the renderer in the game's options screen.

* **Software**: the game uses 8-bit (256-colour) DirectDraw, which modern Windows emulates
  imperfectly. If colours are wrong or the screen flickers, use dgVoodoo2 (below) or set
  *Compatibility > Reduced colour mode: 8-bit* on `HG.EXE`.
* **Direct3D** (`DX5DRAW.DLL`): the most reliable route is dgVoodoo2 (dege.freeweb.hu or
  github.com/dege-diosg/dgVoodoo2). Copy its `MS\x86\DDraw.dll` and `D3DImm.dll` into the game
  folder. Unlike under Wine, current dgVoodoo2 releases are fine on Windows.
* **3Dfx** (`3DFXGEAR.DLL`): needs a Glide wrapper: dgVoodoo2's `3Dfx\x86\Glide2x.dll` in the
  game folder, or nGlide (zeus-software.com). After installing nGlide, tick *Set up 3Dfx* on the
  app's Install & update page: it finds nGlide's `glide2x.dll` in `SysWOW64` (or browse to one),
  copies it in as `glide2x_real.dll` and puts the particle fix in front of it as `glide2x.dll`. With
  the `borderless` fix and 3Dfx selected, **Apply & Play** saves nGlide's *Screen resolution: By
  desktop* and *Aspect ratio: Aspect correction* (`Resolution` and `Aspect` = `1` in
  `HKCU\Software\Zeus Software\nGlide2`), so the game looks the same started from the app or from
  `HG.EXE`. These are nGlide's own settings and apply to every game it runs.
  With a plain wrapper, smoke and dust particles show as black squares; the particle-fix proxy
  below cures that.
* **Direct3D 9 renderer** (`3dfx_hgd3d9.dll`): the community Direct3D 9 renderer. It is a separate
  plugin, not one of the official patch files; installing it makes **Direct3D 9 renderer** available in
  the game's renderer list. It does not use the Glide wrapper.

To build the renderer on Windows, install LLVM, Python 3, and the Windows 10/11 SDK (which
provides the Direct3D 9 headers), then run:

```powershell
.\windows\build-renderer.ps1
```

The script builds and verifies `dist\3dfx_hgd3d9.dll`. It also accepts
`-D3D9IncludePath` if the Direct3D 9 headers are in a non-standard location and `-OutputPath`
to choose a different output file. The DirectX SDK (June 2010) headers are also supported.
Wine is not required for this Windows build. Alternatively, run the **windows-exe** workflow
from the repository's GitHub Actions tab and download its `heavygear-renderer-windows` artifact.
`HeavyGearFixes.exe` already contains the renderer. For script-based setup,
install a separate DLL into the game with:

```powershell
.\windows\install-renderer.ps1 -GamePath "$env:USERPROFILE\Games\HeavyGear" -RendererPath C:\path\to\3dfx_hgd3d9.dll
```

Install the renderer only after the official 1.2 update has completed. The app installs it only when the run
reaches official 1.2. For script-based installation, pass
`-InstallRenderer` (and optionally `-RendererPath ...`) to `apply-patches.ps1` while applying
`-Version 1.2` or `-Version all`. The script rejects renderer installation with `-FixesOnly` or
`-Version 1.1`. The installer verifies the DLL is a 32-bit Windows plugin, places it at
`PLUGIN\3dfx_hgd3d9.dll`, and preserves a previous copy if updating it.

Installing the Direct3D 9 renderer is on by default in the app, and it also selects the
renderer (`DLLFILE.INI`). The box only takes effect where it can work: unless you ticked
it yourself, a setup that does not reach official 1.2 simply skips it instead of stopping with an
error. The renderer is selected only when the game has no renderer selected, or selects the
Direct3D plugin `DX5DRAW.DLL` (which the red-menu fix sets aside); an explicit choice of any other
renderer is left alone, and the install says so. Change the renderer at any time on the app's Play page
or the game's Options > Renderer menu.

### 3Dfx particle fix (proxy `glide2x.dll`)

The proxy sits between the game and your Glide wrapper, draws smoke, dust and fire with correct
transparency, and passes everything else straight through. It needs your own wrapper (nGlide or
dgVoodoo2) as well; it does not replace it. It was developed with nGlide and dgVoodoo on Wine, and
is confirmed on Windows 11 with nGlide 2.10; please report results with other set-ups.

The app carries the proxy: **Set up 3Dfx** on the Install & update page puts your wrapper in the
game folder as `glide2x_real.dll` and the proxy in front of it as `glide2x.dll` (each file it
replaces is kept as a `.bak` copy). To do it by hand instead:

1. Download `glide2x.dll` from the repository's Releases page (or, for a build from any commit,
   from the `heavygear-glide-proxy` artefact of the `glide-proxy` workflow in the Actions tab).
2. In the game folder, rename your wrapper's `Glide2x.dll` to `glide2x_real.dll`.
3. Copy the downloaded file into the game folder as `glide2x.dll`.

To undo: delete `glide2x.dll` and rename `glide2x_real.dll` back to `Glide2x.dll`.

Optional files next to the DLL: `glidefix.cfg` containing the word `nofix` switches the fix off
(the proxy then only forwards); an empty file named `glidelog.txt` turns on call logging (tens
of MB per mission, so delete it for normal play).

## Building the .exe files yourself

`windows\build-exe.ps1` builds `dist\HeavyGearFixes.exe` (contains the patcher, controls, renderer and
music proxy), as well as separate developer executables for script-based workflows (`-Target app|tools|all`).
Building requires Python 3 and PyInstaller; the renderer must first be built with
`windows\build-renderer.ps1` or downloaded from the `heavygear-renderer-windows` artifact, and the music
proxy with `tools/cdaudio/build.sh`. The `windows-exe` GitHub Actions workflow builds the app for
Windows and Linux and publishes both as the end-user downloads. The proxy DLL has its own `glide-proxy` workflow (`tools/glidelog/build.sh`
needs clang, lld and llvm, so it is easiest to use the download).
