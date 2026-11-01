# Heavy Gear engine notes

Collected while building these fixes. Addresses are virtual addresses in the game's own DLLs (the
v1.0 disc build unless a section says 1.2), as a decompiler shows them for your own copy.

The sections below use the fix names of `patcher/hgfix.py` (`--fix` / `--skip`);
`python3 patcher/hgfix.py GAME_DIR --list` shows them all, and its docstring describes each one.

## Build facts
* Built with MSVC 5.0, Nov 17–19 1997 (version 1.0 as shipped on these discs). No debug symbols survive.
* The engine is Activision's Interstate '76 engine. `PLUGIN/I76DRAW.DLL` is its renderer, and the source
  paths left in HGSIM (`C:\projx\Code\sim\Mem\syscache.c`, `sysfile.c`, `MEM\CACHE.C`, `RNDR\MATRIX.C`)
  match that codebase. Community I'76 projects (e.g. Open76) are useful references for shared formats.
* HGSIM statically links the C runtime; HGSHELL uses `MSVCRT.DLL` (so its CRT calls are already named).

## Program flow
* `HG.EXE` is a small host. It reads `lang.ini`, checks files and display depth, then loops between two
  DLLs: `RunShell` @ `0x00402550` loads `HGSHELL.DLL` and calls `ShellMain`; when a mission starts it
  frees the shell and `RunSim` @ `0x004024b0` loads `HGSIM.DLL` and calls `SimMain`; afterwards it
  goes back to the shell. Window messages go to `ShellWindowProc` / `SimWindowProc` respectively.
* The shell (menus, career, gear bay, network lobby via `ANET2.DLL`, Smacker videos via `SMACKW32.DLL`)
  writes the chosen renderer to `dllfile.ini` and builds the sim's options string (`/high /d3d`,
  `/high /3dfx`, `-N=` for network).
* The sim loads one renderer from `plugin\*.dll`.
* Renderer plugin API (exports shared by all four plugins): `CheckFunc`, `GetFuncDesc`, `FirstDevice`,
  `LastDevice`, `GetNumDevice`, `GetSocketCaps`, `Render`, `RenderNoClip`, `RenderRefresh`, `SetState`,
  `SetLumaTable`, `PreloadTexture`, `UpdateTexture`, `SetTexturePalette`, `LockDisplay`,
  `UnlockDisplay`, `RefreshDisplay`, `LostDeviceDisplay`, `RestoreDevice`. A new renderer (e.g. OpenGL
  or Vulkan) would be a DLL implementing this API.

## CD check
`HGSIM!CheckGameplayCD` @ `0x1000138e`: walks `GetLogicalDriveStringsA`, and at the **first** drive where
`GetDriveTypeA == DRIVE_CDROM` it checks for `X:\video\B51MOVIE.AVI`. It returns at that first CD drive
either way, so a second CD drive is never checked. HGSHELL has a similar check (search for
`B51MOVIE.AVI` / `GetDriveTypeA`). The cutscene AVIs (Indeo 5, `IV50`) are played from that drive.
The shell's movie players take their folder from three (v1.2) or two (v1.0) scans that format `%c:\%s\`
with the CD drive's letter and the name `video`; a fourth, which returns a bare letter for a run-from-disc
layout, never matches on a disc-1 install. The `nodisc` fix (see `hgfix.py`) rewrites these in place:
`cmp eax,5` -> `cmp eax,eax`, the format -> `.\%.*s\`, and the sim's probe -> `X\..\video\B51MOVIE.AVI`.

## Music (CD audio)
Only `HGSIM.DLL` plays music, in one module (v1.0 `0x1009de00`-`0x1009ec00`, v1.2 around `0x1008xxxx`) through
`mciSendCommandA` and `aux*Volume`, all from `WINMM.dll`. Setup: pick the aux device of type CD audio (else line in),
`MCI_SYSINFO` (device count for type `0x204`, then the name of device number *n*, where *n* is the CD-drive count kept by
`CheckGameplayCD`, which is why the `nodisc` fix keeps that count at 1), `MCI_OPEN` that name, `MCI_SET` time format
TMSF, `MCI_STATUS` number of tracks, then each track's start (`MCI_STATUS` position with `MCI_TRACK`), plus a sentinel
(last track + 1). Everything after that is whole tracks: `MCI_PLAY` from one start to the next, `MCI_STATUS` mode
(stopped / playing / paused) polled to loop or move on, current position for the track number, `MCI_PAUSE` /
`MCI_RESUME` / `MCI_STOP` / `MCI_CLOSE`, and the volume through `auxSetVolume`. `tools/cdaudio` answers exactly these
calls from `MUSIC\TRACKnn` files (see its README); `hgfix --fix music` points HGSIM's WINMM import at it.

## Resource system (`syscache.c`)
Load order for an asset `NAME.EXT` (`HGSIM` ≈ `0x100b9xxx`–`0x100bbxxx`):
1. in-memory cache (`CacheLookup` @ `0x100baf3f`), sized per type by `CACHE.INI`
2. a loose file in the current directory, `NAME.EXT<c>` then `NAME.EXT`  ← mods go here
3. directories listed in an optional text file called `where` (`LoadWhereSearchPaths` @ `0x100b9fa5`,
   `OpenFromWherePaths` @ `0x100bae0a`), used when no PRJ is open
4. the `HEAVYG.PRJ` archive

### HEAVYG.MAP / HEAVYG.PRJ
Summary of the layout:
* MAP: `"YL\0\0"`, type table (`ext[4]`, `count`), 2 × 16-byte decompressor names (`pkware.dll`, `zlib.dll`),
  then 20-byte entries `{name[8], ext[4], u32 offset, "NONE"}` sorted by name (strcmp), with extensions
  in reverse type-table order within a name. Six names appear twice in the original (harmless).
* PRJ entry: `tag[12]` (`C:\PRJ\` + first letter + ext), `u16 method` (0 stored / 1 PKWARE DCL implode /
  2 zlib), `u32 unpacked`, `u32 packed`, data. 15,824 zlib, 2,302 stored, 1,419 PKWARE (all PCX images).

### Formats seen so far
* `BWD`: chunked "world description" with named chunks such as `scenario_table`, `mission_table`,
  `gp_chassis_table`, `object`, `gamepiece`, `navpoint`, `orders`, `formation`, `music`, `include`,
  `rep/endrep`, `block/elseblock/endblock`. Defines maps and missions.
* `BRF`: plain-text mission briefings.
* `GDF`: gear (mech) definitions: template name plus skeleton part names (`hips`, `left_upper_leg`, …).
* `.VDF` (loose files): plain-text gear hierarchy (`GEAR.VDF`, `MAMMOTH.VDF`, `NAGA.VDF`).
* `PAR`: plain-text parameters (`SKYGND.PAR`).
* `PCX`/`PCXX`: standard 8-bit PCX. `WAV`/`WAVX`: standard RIFF WAVE (8-bit 22 kHz).
* Not yet mapped: `3DI`, `ODF`, `SDF`, `WTB`, `XEL`, `TEX`, `MLT`, `TLT`, `SHP`, `FNT`, `COL`, `TBL`.

## Config files
* `HG.INI`: error-code strings, plus a `[Debug]` section that can turn on engine logging (`ToLog=1`,
  `Logfile=kra.log`). The cache also writes `hgdebug.txt` / `dbugcch%d.log` in some debug paths.
* `CACHE.INI`: per-type cache hash/size table. `DLLFILE.INI`: selected renderer.
  `*.MAP` (loose ones such as `KEYBOARD.MAP`) and `GIDDIWIN\*.CPC`: input/controller mappings.

## Decompiler output conventions
* `FUN_xxxxxxxx`: unnamed function at that address. `thunk_X`: jump stub to import `X`.
* `uRamXXXXXXXX` / `iRam…` / `pcRam…`: global variables at that address (prefix shows the guessed type).
* `0x1014b2b8 /* "heavyg.prj" */`: a pointer to a string in the binary, with its text inlined.
* About 90 tiny functions (mostly jump-table fragments that function discovery mistook for function
  starts) produced no output. Their addresses are under `failed` in `*.symbols.json`.

## Timing (why things run too fast) and the FPS patch
* Sim master clock: `FUN_100010af` converts `timeGetTime()` into 5 ms ticks (`iRam10153380`).
  `FUN_100025ae` turns ticks into game time `iRam1015dc78` and the frame delta `iRam1015dc80`.
  Real-time parts are correct, but many animations step once per frame.
* The sim's own limiter, command-line `-F=<fps>` (`iRam1015dc94 = 181 / fps` ticks per frame),
  waits on the tick counter without advancing it, so in this Windows build it would hang.
* The shell's menu loops (e.g. around `0x10170214`) have no timing at all; each frame calls
  `FUN_1002fc44` (input pump).
* `patcher/hgfix.py` hooks `HGSHELL!FUN_1002fc44` and `HGSIM!FUN_100025ae` with a limiter that
  waits for the next `1000/fps` ms boundary of `timeGetTime()`. It uses each DLL's own
  `return timeGetTime();` helper (`0x10183b5b` / `0x10002b62`) with relative calls, so it
  doesn't depend on the load address.
* `--sim-fps 60` (limiter period 17 ms, about 58.8 fps) was tried in play on Wine with the Direct3D 9 renderer plugin and ran well; no per-frame animation was seen running too fast.
  Full command: `hgfix.py GAME --fix limiter --fix display --fix anet2 --fix partdepth --sim-fps 60` (menus stay at 30).
* The sim's option string comes from `hgprm.cfg` (offset 0x240), which the shell rewrites
  before every mission and `HG.EXE` passes to `SimMain`.

## Black screen after a mission (display-mode fix)
* After a mission, `HG.EXE` frees HGSIM and reloads HGSHELL (`debug.log`: "Returned from Sim" →
  "Entering Shell"). Under Wine the screen came back 32-bit while the shell's DirectDraw surfaces
  are 8-bit (P8), so `FUN_10179df0` (if `IsLost()` then `Restore()` the primary and back buffer)
  failed forever: `ddraw_surface7_Restore Display mode format 0x77 doesn't match surface format 0xa`.
* `DDRAW_Init` (≈ `0x101776xx`) only calls `SetDisplayMode` when the DirectDraw object is first
  created, storing the size in `0x10252768` / `0x1025276c`.
* `patcher/hgfix.py` also hooks `0x10179e1c` (just after `primary->Restore()`) and counts
  consecutive failures; after 20 in a row it calls `IDirectDraw::SetDisplayMode(w, h, 8)` and
  retries. A few failures are normal: even the unmodified game logs ~6 just before the intro, after
  which the movie code rebuilds DirectDraw in 16-bit. Forcing 8-bit on those broke the intro video.
* The shell patches live in an added section `.hgfix` (code + the counter at its start).
  HGSHELL is usually rebased (ANET2.DLL takes 0x10000000), so the code finds its own address with
  call/pop, and the relocation entry under the overwritten instruction is disabled.
* **Red shell after a mission (Windows, not Wine): cause found by logging DirectDraw calls.** Windows runs
  `HG.EXE` under the `DWM8And16BitMitigation` compatibility layer (`apphelp.dll`), which the shell
  needs for its 8-bit mode (`SetDisplayMode(640,480,8)` is `E_NOTIMPL` without it). Right after
  `DDRAW_Init` the shell probes the Direct3D plugin (`HGSHELL.DLL+0x3a544` → `dx5draw.dll+0x10b3`
  → `DirectDrawCreate`, v1.2 patched, offsets from the load address); the plugin creates and
  releases a second DirectDraw object, and the layer then drops the primary surface's palette
  (`GetPalette` = `DDERR_NOPALETTEATTACHED`, `SetPalette` = `DDERR_INVALIDPIXELFORMAT`), showing
  the picture as palette indices in the red channel. At start-up the same probe is followed by the
  intro movie and a second `DDRAW_Init`, which is why the first menu is fine. Renaming
  `PLUGIN\dx5draw.dll` avoids it: that is the `dx5draw` fix, on by default on Windows. Confirmed on one machine so far.
* `HG.EXE` byte at file offset 0xBE20 (VA 0x40e020) selects its debug output:
  0 = off, 1/4 = `debug.log`, 2 = OutputDebugString, 3 = message box.

## Shell in a borderless window (`borderless`)
The shell's display library has an unused windowed GDI mode (mode 5) that works once two original bugs are patched;
the `borderless` fix runs menus and movies in one scaled borderless window with no display-mode switch. Details,
addresses and test results: [research/shell-display.md](research/shell-display.md).

## Version 1.2 (official patch)
* 1.1 (`hgp187d.exe`, internal version 1.87) and 1.2 (`HGPATC12.EXE`) are RTPatch delta patches. They
  locate the game via `HKLM\Software\Activision\Heavy Gear` (values `EXE` = exe name, `FTP` = SKU
  `HGEARW95`; subkeys are version numbers, the lowest one is "the" version) and
  `App Paths\<EXE>` (full path to HG.EXE). 1.2 accepts versions <= 1.2 or exactly 1.87.
  The 1.1 patcher launches the game when it finishes.
* 1.2 rebuilt HG.EXE, HGSHELL.DLL and HGSIM.DLL. HGSIM is a non-incremental build (no `jmp` stubs),
  so the sim limiter redirects the clock's only call site instead of a stub. Addresses used by
  `patcher/hgfix.py`:
  | | v1.0 | v1.2 |
  |---|---|---|
  | shell input pump | `0x1002fc44` | `0x100305ce` |
  | shell timeGetTime helper | `0x10183b5b` | `0x1018728b` |
  | lost-surface handler / hook | `0x10179df0` / `+0x2c` | `0x1017d500` / `+0x2c` |
  | IDirectDraw* / primary | `0x102506f4` / `0x102506f8` | `0x10259974` / `0x10259978` |
  | width / height / last result | `0x10252768` / `…6c` / `…70` | `0x1025b9e8` / `…ec` / `…f0` |
  | sim clock step | `0x1002a983` (stub `0x100025ae`) | `0x1001ff23` (call at `0x10070d0e`) |
  | sim timeGetTime helper | `0x100b8fdb` (stub `0x10002b62`) | `0x100a13bb` |
* New loose data: ~1,100 textures and material tables in `C:\HeavyGear\patch\`, updated mission
  `BWD`s, `SKYGND.PAR`. `HEAVYG.MAP/PRJ` are unchanged.
* **Freeze at mission start (1.2):** before a single-player mission `HG.EXE` unloads `ANET2.DLL`
  (`FUN_004011e0`: `do FreeLibrary(h) while (ok)`). The 1.2 `anet2.dll` is packed (entry in a
  `.dllent` section, real code unpacked at load) and waits for one of its threads while unloading;
  under Wine that thread can't exit while the loader lock is held, so the main thread hangs inside
  `FreeLibrary` (backtrace: `hg+0x133c`). `patcher/hgfix.py` turns the call at `0x401339`
  (`push eax; call edi`) into `xor eax,eax; nop`, so ANET2 just stays loaded, as it already does
  for network games. 1.0's ANET2 unloads fine.
* **Black / half-drawn debrief, root cause (found with `trace+ddraw,trace+system`):** the shell's
  `DDRAW_Init` calls `SetCooperativeLevel(hwnd, 0x51)` and then `SetDisplayMode(640,480,8)`. Wine's
  ddraw builds its wined3d swapchain inside SetCooperativeLevel from the mode current at that time
  (the 32-bit desktop), and because ddraw uses `WINED3D_RESTORE_MODE_ON_ACTIVATE`,
  `wined3d_swapchain_activate()` re-applies that stored mode whenever the window is activated. After a
  mission the activation arrives just after the shell has drawn its first frame →
  `ChangeDisplaySettings(…32 bpp…)` → `device_parent_activate` → every 8-bit surface lost
  (`Display mode format 0x77 doesn't match surface format 0xa`), and the debrief background, drawn
  once, is wiped. 1.0's debrief happened to redraw after the fallback restore; 1.2's doesn't.
  Fix (`patcher/hgfix.py`, both versions): right after `SetDisplayMode(w,h,8)` on DDRAW_Init's
  8-bit branch (the `mov [result],eax` at v1.0 `0x10177df4`, v1.2 `0x1017b507`), if it succeeded,
  call `SetCooperativeLevel(ddraw, hwnd, 0x51)` again so the swapchain is rebuilt with the 8-bit mode.
  Side effect: the display now really is 8-bit when the shell builds a movie player
  (`FUN_10022c28` in 1.2 / `FUN_10022418` in 1.0: `CoCreateInstance(CLSID_FilterGraph)`), and
  DirectShow set up under 640×480×8 fails every frame (`err:d3d:cpu_blitter_blit Failed to blit`,
  black intro). Before the fix Wine had already knocked the mode back to 32-bit there by accident.
  So that function's entry now calls `RestoreDisplayMode` on the shell's DirectDraw object first. (Two wrong guesses first: the DX5DRAW
  `CheckFunc` probe, and the 3Dfx plugin's failed load; neither was involved.)

## 3Dfx / Glide renderer under Wine
* `PLUGIN\3DFXGEAR.DLL` imports only `glide2x.dll`. Wrappers tried (in `wrappers/`, installed by
  `linux/setup-glide.sh` or nGlide's own installer):
  * dgVoodoo2 **2.87.5** (latest on GitHub): crashes on garbage pointers inside `grSstWinOpen` /
    texture uploads with every backend (DXVK d3d11, Wine d3d11, Wine d3d12). Matches WineHQ bug 58731
    (dgVoodoo2 > 2.80 broken under Wine).
  * dgVoodoo2 **2.79.3** (dege.freeweb.hu) + DXVK 3.1.1: works.
  * nGlide 2.10 (`wine nGlide210_setup.exe /S`, installs into syswow64): works.
  A `Glide2x.dll` in the game folder takes precedence over the system one.
* The game calls `grSstWinOpen(hwnd = 0, 640x480, …)`.
* **Particles drawn as black squares (both wrappers, not in D3D): solved in `tools/glidelog/`.**
  Root cause, found with the logging proxy: the particle textures are keyed P_8 textures whose palette
  top byte holds the transparency (0xFF = transparent, lower = more opaque), and the chroma-key colour
  (palette entry 255) does not equal the black background index, so the driver keys the wrong colour.
  The sim and plugin patches tried earlier (re-sending the key, masking its top byte, the cache-flag
  lead in `FUN_10002410`) were dead ends; dgVoodoo and nGlide behave identically.
  The fix is a proxy `glide2x.dll`: it converts each keyed P_8 texture to AP_88 (alpha = 255 - top byte,
  key texels 0), keeps it in the top 128 KB of texture memory (the game leaves it free) and turns
  the chroma key off. Most particle draws are not keyed, though (about 160,000 quads against a few hundred
  keyed ones in one mission's log): they are drawn with the key off, SRC_ALPHA/1-SRC_ALPHA, alpha from the
  texture, which a P_8 texture lacks, so they came out solid until the proxy converted those too (2026-10-31).
  After an alt-tab the game closes and reopens Glide and re-uploads its particles itself as single-level
  AP_88, which is why they looked right from then on. Smoke, dust and fire are confirmed fixed under nGlide 2019
  with Wine 11, and under nGlide 2.10 on Windows 11 from the first frame. The
  remaining stepped contours in the smoke come from the original low-colour palette art.
  Particles use render types 7/8/0xC/0xD (`grAlphaCombine(SCALE_OTHER, ONE, ITERATED, TEXTURE)`,
  SRC_ALPHA/1-SRC_ALPHA blend). D3D (`DX5DRAW.DLL`) calls `SetColorKey` with the palette key and
  toggles COLORKEYENABLE per draw, which is why D3D looked right.
  Online: the DxWnd forum's Heavy Gear thread reports the same symptom with dgVoodoo on Windows.
* `tools/glidelog/` builds a logging `glide2x.dll` proxy (clang + lld-link, see its README). Put it in
  `C:\HeavyGear` with the real wrapper copied next to it as `glide2x_real.dll`; it writes
  `C:\HeavyGear\glidelog.txt` (chroma-key mode/value vs. palette, texture sources, combine and
  blend state at the first draw of each texture, triangles per frame; only if `glidelog.txt` exists).
