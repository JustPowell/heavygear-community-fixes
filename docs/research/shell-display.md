# Shell display: refresh modes, GDI mode and the borderless window

Research behind the `borderless` fix (`patcher/hgfix.py`). Addresses are
v1.2 (the build the installed game runs) unless marked; v1.0 addresses are still to be found ("to find" below).

## Refresh modes and drivers (HGSHELL)

The shell's display library opens the screen through one function, `display_open(mode, ?, ?, w, h, menu)` at
`0x101797cb` (v1.0: to find). `mode` indexes a table of seven refresh-mode records at `0x1023f830`; each record holds
its number, a driver number, and five function pointers: open, close, full present, rectangle present, stretch present.
The drivers (table at `0x1023f820`) are DirectDraw (modes 0-3), DISPDIB (4), GDI (5) and a fourth, null-like one (6).
Each driver record holds a window type (1 = full screen, 2 = windowed) and the window style to use.

The shell always asks for mode 3 (DirectDraw, 640x480x8), from three places: start-up (`0x1003022b`), movie start
(`0x10031c86`) and after the movie (`0x10031d52`). Each is a `push 3` just before the call.

Mode 5 is a complete windowed path: an 8-bit DIB section with a colour table, a memory DC, and `BitBlt` to the
window's DC. It was probably never used by the shipped game, and it carries two bugs that stop it from working:

1. **Draw gate.** The routine at `0x10030607`, called before every frame is drawn, draws only when the IDirectDraw
   pointer (`0x10259974`) is set. Under GDI that pointer stays 0, so nothing is ever drawn. The GDI DC (`0x102599a0`,
   set by the GDI open and cleared by its close `0x1017d757`) serves the same purpose of "display is open".
2. **Present result.** The GDI presents (`0x1017dd3b` full, `0x1017dd9e` rectangle, `0x1017de8e` stretch) treat the
   blit as successful only when its return value equals the canvas height (`0x1025c790`). `BitBlt` returns TRUE (1),
   so every present "fails"; the GDI open checks its first present, closes itself and the library falls back to the
   next mode. The correct test is "non-zero".

## The window

`display_open` reads the screen size with `GetSystemMetrics`. If the screen is no larger than the canvas it uses the
driver's full-screen style (`WS_POPUP`); otherwise it writes the windowed style `0xca0000` (title bar, no
`WS_CLIPCHILDREN`) at `0x101798bd`, sizes the window around the canvas with `AdjustWindowRect` and centres it.
The window rectangle is kept at `0x1025c300` and applied with `SetWindowPos` by `0x1017a02c`; the canvas size is kept
at `0x1025c78c`/`0x1025c790`. The decision point is `0x10179897`; both branches meet again at `0x10179930`.

HG.EXE creates the shell's window (646x512, centred, `0xca0000`) and shows it with `ShowWindow(SW_MAXIMIZE)` at
`0x40255b`. A maximised window keeps that state through later style changes: after a DirectDraw movie the window
collapsed to a title bar. The maximised state also hid a dependency (see Mouse).

## Mouse

Two paths, both in client coordinates of the 640x480 canvas:

- A poll in the menu input pump (`0x10027396`): `GetCursorPos`, `ScreenToClient` (call at `0x100273d7`), then a
  check (`0x100274dd`, called at `0x100273e8`) that the point lies inside a rectangle the mouse object took with
  `GetWindowRect` when it was created. That rectangle is in screen coordinates and is the window HG.EXE created; the
  check only matched every point because HG.EXE maximised that window. Buttons come from `GetAsyncKeyState`.
- Window messages `WM_MOUSEMOVE` to `WM_MBUTTONDBLCLK` in the shell's window procedure all pass their lParam through
  one routine, `0x10034ab6`, which subtracts an offset and packs the point again. Both paths are used.

A cursor-warp routine (`ClientToScreen` + `SetCursorPos`, `0x10027266`) exists but nothing calls it.

## Movies

For a full-screen movie the shell opens a black pop-up the size of the screen, `HGShellMovie`, shown with
`SW_SHOWNORMAL` (the site the `moviebg` fix changes), and plays the file through DirectShow in a child of the shell
window (`IVideoWindow`: `WS_CHILD`, 0, 0, 640x480, owner = shell window; `IBasicVideo` destination = twice the video
size; set up in `0x10022dce`).

**Why movies looked black in GDI mode.** The backdrop is a top-level window created after the shell window, so it is
above it. With DirectDraw the shell's exclusive full-screen mode covered it; in a normal window it covers the shell
window and the video child, and it takes every mouse message. Hidden, the intro shows. (In the tests the first
clicks after start-up only skipped the logo and the intro, which played unseen behind the backdrop.)

**Scaling the video.** DirectShow's video window is moved onto the 4:3 rectangle with `IVideoWindow::SetWindowPosition`,
and the picture's destination (`IBasicVideo` Get/SetDestinationPosition) is scaled by rectangle / canvas, right after
the game has given the window its owner (`0x10022f47`). Wine's renderer here is the VMR7 presenter: it ignores the
destination and blits the YUV frame to the DirectDraw primary over the whole client area, through a clipper.

**Windows 98 mode breaks it under Wine.** When the program reports a 9x Windows version, Wine's DirectDraw clipper
adds the DC origin to a window region that is already in screen coordinates, so a child window at (x, y) is clipped
as if it were at (2x, 2y). With the video at x = 320 the clipped source rectangle starts at an odd pixel, which the
YUV surface (2x1 blocks) refuses: every frame fails with `D3DERR_INVALIDCALL` and the video stays black. At (0, 0),
the game's own placement, the bug never shows. Our Linux setup used to make HG.EXE report Windows 98 as a general
precaution; it no longer does, and the launcher removes the old setting. With Wine's default version the intro plays
scaled into the rectangle (2026-10-27, 2560x1440 desktop).

## What `borderless` changes (v1.2)

| Where | Change |
|---|---|
| `0x1003022b`, `0x10031c86`, `0x10031d52` | `push 3` -> `push 5`: GDI mode |
| `0x1003061f` | draw gate tests the GDI DC instead of the IDirectDraw pointer (still an image address: its relocation stays) |
| `0x10179897` | jumps to the window routine: the desktop size is stored the first time; the window becomes `WS_POPUP \| WS_CLIPCHILDREN` covering the desktop; the canvas stays as asked; the largest canvas-shaped (4:3) rectangle is centred and four black bars are worked out around it |
| `0x1017dd3b`, `0x1017dd9e` | full and rectangle present jump to one routine: the bars are blacked out (`BitBlt` with `BLACKNESS`) and the canvas is stretched into the rectangle (`StretchBlt`), returning 0 on success |
| `0x1017dee1` | stretch present's result test becomes "non-zero = success" (relocation disabled) |
| `0x100273d7` | the poll's `ScreenToClient` call goes to a routine that calls it and maps the point to the canvas (relocation disabled) |
| `0x100273e8` | the poll's window-rectangle check always passes (the mapped point is always on the canvas) |
| `0x10034ab6` | entry: lParam is mapped to the canvas before the routine runs |
| `0x10031ac8` | the movie backdrop is created hidden (same byte as `moviebg`) |
| `0x10022f47` | after the movie's video window gets its owner: window moved onto the rectangle, picture destination scaled |
| HG.EXE `0x40255b` | `ShowWindow(SW_MAXIMIZE)` -> `SW_SHOWNORMAL` |

Mapping: x' = (x - left) * canvas width / rectangle width, clamped to 0..639; the same for y. A pointer in a bar
therefore reaches the shell as the nearest point on the picture's edge.

Stretch mode: the shell does not import `SetStretchBltMode`, so the DC keeps its default (`BLACKONWHITE`). That
mode differs from `COLORONCOLOR` only when shrinking; enlarging replicates pixels either way.

The code lives in an added section `.hgbdr`, written position-independently (`call`/`pop` for its own address), as
the other fixes do.

## Checks so far (Wine 11.20, 2560x1440 virtual desktop)

- Window: `SetWindowLongA(GWL_STYLE, 0x92000000)` and `SetWindowPos(0, 0, 2560, 1440)`; desktop 2560x1440 stored,
  picture at x = 320, 1920x1440.
- The menu draws scaled with correct colours; the intro is visible (unscaled). Mouse positions match the buttons.
- No `DirectDrawCreate` from HGSHELL during start-up (relay trace); the remaining calls come from the DX5DRAW plugin
  probe and from DirectShow.

## Software missions (HGSIM)

HGSIM has its own copy of the display library with the same layout: `display_open` at `0x1002bf8b`, mode table
`0x1010f8a0`, the full-screen/windowed decision at `0x1002c057` (both branches meet at `0x1002c0f0`), GDI window style
`0x1011ded0`, window rectangle `0x107edf50`, canvas `0x107ee3cc`/`0x107ee3d0`. Its GDI driver presents with
`SetDIBitsToDevice`, which returns the number of scan lines, so its result test (against the height) is correct: the
shell's present bug is not in the sim. A screen-shake/static effect (`0x1006e801`) draws through the same call at
offsets.

The sim opens its display twice per mission: mode 5 at the screen's size (`0x10070023`), then the mission mode
(`0x10070893`) from a variable at `0x1010f674`. Its initial value is -1 (a DirectDraw mode, used by the software
renderer; a command-line switch parsed at `0x10020746` can set it). The hardware paths set it themselves: 0 for
DX5DRAW (which uses the sim's DirectDraw object), 6 for plugins with their own output (hgd3d9, 3DFXGEAR).

`borderless` changes the initial value to 5 (GDI), gives the sim the same window routine as the shell, and sends all
eight `SetDIBitsToDevice` calls of the GDI driver to a routine that maps the destination into the 4:3 rectangle (each
edge mapped, so adjacent pieces meet) and draws with `StretchDIBits`; on a whole-canvas draw it first blacks out the
bars with `StretchBlt` (`BLACKNESS`, no source; the sim does not import `BitBlt`). Tested 2026-10-27 at 640x480: the
software mission fills the rectangle, the shake effect and HUD are right, alt-tab during the mission is fine, and the
debrief and menus come back.

With full-screen DirectDraw (the unpatched software path, and DX5DRAW) alt-tab is broken under Wine's emulated modes:
on deactivation Wine's DirectDraw puts the desktop mode back and resizes the window to it (`device_parent_mode_changed`)
before minimising it, so the size restored on reactivation is the desktop's, inside the re-applied 640x480 mode; the
window is then scaled far off the screen (traced 2026-10-27).

For DX5DRAW (scaled through emulated modes, which the launcher turns on for that renderer only) `borderless` hooks
`SimWindowProc` (`0x10071397`): on `WM_PAINT` a window that is not minimised and not the screen's current size is
resized to it. `WM_ACTIVATEAPP` and `WM_SIZE` are no use: Wine's DirectDraw restores the window while it keeps the
window's messages to itself, and the game's procedure sees neither in the right order (two attempts, traced). The
repaint that follows the restore does reach it. Checked in an x86 emulator and confirmed in play (2026-10-29).

3DFXGEAR asks Glide for 640x480 (`grSstWinOpen` resolution 7). nGlide 2.10 (Direct3D 9 back end) at its default
"By app" resolution draws that picture in the bottom-left corner of the full-screen window. Through Wine's emulated
modes the mission is scaled, but a black unscaled 640x480 box sits in the top-left corner until the first alt-tab.
nGlide's own settings fix both: `Resolution` 1 ("By desktop") renders at the desktop's resolution and `Aspect` 1
("Aspect correction") keeps 4:3 with bars. They live in `HKCU\Software\Zeus Software\nGlide2` or in the
environment variables `NGLIDE_RESOLUTION` and `NGLIDE_ASPECT`; the launcher sets the variables. In nGlide's
configurator lists the first item is 0: Backend 0 automatic, 1 DirectX, 2 Vulkan; Aspect 0 entire screen, 1 aspect
correction, 2 integer rendering, 3 integer scaling; Resolution 0 by app, 1 by desktop, then fixed sizes from 640x480
up. Tested 2026-10-29: the mission fills the 4:3 area at full resolution, no black box.

DX5DRAW has no size of its own: it draws into the sim's DirectDraw set-up, and the sim starts a hardware plugin only
when its own size is exactly 640x480 (`0x10070217`; the plugin's start call gets 640 and 480 in its parameter
block). Above 640x480 it would need the sim's 1024x768 driver (task 7.1) and that check patched.

**Mouse after alt-tab.** The sim reads the mouse as a cursor position in its window (`0x10069c48`): while active it
confines the cursor to the top-left canvas-sized area of the client (`ClipCursor`, rectangle from `0x10069e21`),
centres it once, and ignores positions outside that area; buttons come from `GetAsyncKeyState`. It releases the
confinement when `WM_ACTIVATEAPP` says it lost focus and confines again when it comes back, or when the flag at
`0x10148e98` is set (refresh-mode changes set it). With 3DFXGEAR under Wine the sim never sees the alt-tab (Wine's
Direct3D keeps the activation messages, as with DX5DRAW), so on return the cursor is free; in a 640x480 window that
goes unnoticed, but in the full-screen `borderless` window it leaves the 640x480 area and movement stops while clicks
still work (tested 2026-10-29; hgd3d9 was not affected). `borderless` sets the flag in its `WM_PAINT` hook, so the
repaint after the switch confines and centres the cursor again (confirmed in play with 3DFXGEAR, 2026-10-29).

## Cost at 3840x2160

The shell presents only when the picture changes (8 presents from start-up to a still main menu, including the
movie transitions). Each present's `StretchBlt` of 640x480 into 2880x2160 returned within the 1 ms resolution of a
timestamped relay trace (Wine 11.20), so the limiter's 33 ms frame is never at risk from scaling.

## The sim's resolution (HGSIM)

HGSIM has its own copy of the display library. The sim's resolution comes from a driver name chosen at
`0x1007198c`: `MCGA.DLL` 320x200, `VESA480.DLL` 640x480, `VESA768.DLL` 1024x768. The name is read from `hgsnd.cfg`
at offset `0x48`; the shell's detail option writes `mcga.dll` or `vesa480.dll` there (strings at `0x1022d850`,
`0x1022d868`, and `0x10238600` for the mission set-up). The hardware plugin path is set up only at exactly 640x480
(in `SimMain`, function `0x1006fab3`), so other sizes are software only. `I76DRAW` gets its target buffer with every
call and holds no size constants. With `vesa768.dll` a software mission crashes within about ten seconds.

**Why 1024x768 crashes (2026-10-29).** Before a mission `0x100966ba` picks a resolution index (`0x10188b44`) by
matching the screen against three sizes at `0x1011ffd0` (319x199, 639x479, 1023x767; nearest within a distance of 7,
the limit set at `0x100966c1`, loop bound at `0x100966da`). The index selects the HUD and cockpit data: 30 HUD
rectangles per layout from `0x1010b800` (600 bytes per layout, two cockpit variants per size), HUD image names from
`0x1010c520` (`HNLOMPS0`...), fonts from `0x1010e2e0` (`SIMFNTLO`, `SERPDEUS`) and sizes from `0x10123db0`. Every
one of these tables has entries for only the first two sizes, so at 1024x768 (index 2) the sim reads past their ends.
The rectangles it then converts from 320x200 units (`0x1007629f`, divide by 319 and 199) contain unrelated data;
the divide overflows (reported as `EXCEPTION_INT_DIVIDE_BY_ZERO` at `0x100762c1`, with text such as `MPS0` in the
dividend) and the game's handler then crashes. To reproduce, note that the shell writes its own driver name
(`0x1022d850`, `0x1022d868`, `0x10238600`, all `vesa480.dll` in v1.2) into `hgsnd.cfg` at every mission start,
so editing the file alone runs the mission at 640x480.

Limiting the picker to the first two sizes and accepting the nearest at any distance (two changes at `0x100966c1`
and `0x100966da`) stops the crash: the mission runs at 1024x768 with the 640x480 HUD data. The HUD is then wrong:
element positions are fractions of the screen and move out to 1024x768, but the HUD art is drawn at its 640x480
pixel size, so elements are small and misplaced relative to their backgrounds (tested in play, `borderless`, GDI).
Larger software sizes need the HUD's drawing scaled as well (task 7.3).

## Combat Variables screen (HGSHELL v1.2)

From the v1.2 decompilation (2026-10-29); "confirmed" = traced in the code, "inferred" = read but not chased.

Build: `FUN_10163a91` builds the screen and puts a container `FUN_100277c5(..., 0x570, -1, 0x10, 0xb)` in it:
menu id `0x570`, no parent, 16 child slots, 11 filled first; the screen's object keeps the container at `+0x100`
(confirmed).

Rows: eleven selector rows, added with the container's `+0x24(index, row)` at indices `0`-`10` (confirmed against
the build calls). Each row is a `0xb6`-byte object made by `FUN_100122e5`, which takes four consecutive 41-byte
layout records from `.rdata` (row 0's four addresses are `0x101ebca2`, `0x101ebccb`, `0x101ebd1d`, `0x101ebdc1`,
exactly 0x29 apart; confirmed) - per the design, value field, left arrow, right arrow and spin image, in the
same rectangle-plus-PCX record format the main menu's buttons use. Items are added with the row's `+0x44(label)`;
labels come from `FUN_100245c6(text, font, item id)` in the game's font (`FUN_100242d0(9, 0xfe)`), and the
Graphics Type row is fed from the renderer plugin list ("Software 640" as the software entry, other plugins
labelled by their `GetFuncDesc`). A row keeps its current item at `+0x10`, read by `FUN_100128ca` (confirmed);
`+0x4c` sets the item and `+0x20` refreshes the row. Row ids run `0x571`-`0x5de` in build order, buttons
`0x5df`-`0x5ee`; rows 0-3 (graphics type, sound quality, and the first two toggles) are outside the
Default/Override handlers.

Buttons live in the same container at `0xb`-`0xf`: `0xb`/`0xc` the Override pair (`FUN_100145f3` control with
its own message handling plus a `FUN_1000fe8f` wrapper holding nine click handlers, art record `0x101ecf0d`,
painted `B64OVRD/OVERR/OVERH/OVERS`), `0xd` Default (`FUN_1000f68f` button, class `0x101a6ba0`, art record
`0x101ece69`, painted `B64DFLT/D/T/H/S`), `0xe` Accept (art `0x101ecfb1`, `B64ACCT*`), `0xf` Cancel (art
`0x101ed055`, `B64CNCL*`): record addresses and PCX names read from `.rdata`, button/slot pairing inferred from
the build order. A `FUN_1000f68f` button carries a click-handler table (entries nine dwords apart: press code 8
at `+0`, handler pointer at `+5`, a flag byte at `+4`, filled by `FUN_1000dbf4`; confirmed) and its message
method runs the handlers on a press.

Accept: the click handler object is built by `FUN_100e3bae` (keeps all 11 rows; vtable `0x101ae288` has exactly
one method, from the vtable dump in `.rdata`); that method is `FUN_100e3c57`. Confirmed from decomp: it reads
each row's current item through `FUN_100128ca`, maps the Graphics Type row to the driver name `mcga.dll` or
`vesa480.dll` (strings at `0x1022d850`, `0x1022d868`), writes the shell settings block at `+0x17670` (0x17 bytes)
and `+0x1769e` (0x6c bytes), and the writer then names `hgdif.cfg`, `hgnet.cfg`, `hgsnd.cfg`. The design's claim
that the driver name sits at `hgsnd.cfg` offset `0x48` was not re-checked.

Load: `FUN_100e3f79` is the single method of the class built by `FUN_100e3ed0` (vtable `0x101ae298`, all 11 rows);
it reads the saved settings and sets every row through `+0x4c`. Confirmed from decomp. The Cancel button runs
this object (alongside a `FUN_10014cdf(..., 3)` entry), which is why leaving the screen restores saved values;
the same method serves when the screen opens (inferred use, per the design's wording).

Default: clicking button `0xd` runs its one click handler, an object built by `FUN_100e76b6` holding rows
`4`-`10` (confirmed). Its only method, `FUN_100e7962`, is confirmed from decomp: it probes the CPU through
`FUN_10023101` (which also records a "not GenuineIntel" flag at `0x102fd300`, set by the cpuid check in
`FUN_1002328a`) and reads the CPU MHz with `FUN_1003521c` (registry `~MHz` or a CPUID timing fallback), takes
166 when the flag is set and 200 for class >= 6, then picks the preset record from the table at `0x101c5888`
(39-byte records, speed keys 88, 164, 198, ...) whose key is the largest not above the speed. It sets each of
rows `4`-`10` with `+0x4c` to the record's preset item - the record's flag bytes choose the off/on pair for the
six toggle rows, and the last row takes one of the six speaker items `0x17`-`0x1c` - and runs each row's `+0x20`.
Rows `0`-`3` keep their items. Default touches no cfg file: it restyles the rows only, and Accept is still
needed to store them.

Row cycling: every row also has click and keyboard handlers made by `FUN_1001c2ba(row, screen, key)` that step
the row with `FUN_100126c8`/`FUN_100126e0`; the container registers two key sets (codes `0x1e` and `0x2b`) at
indices 0-6, and the Override control's wrapper re-registers the same row handlers for `0x2b` (confirmed from
the build and the handler class).

## To find

- v1.0 addresses for everything above.
- The sim's handling of the shell window.
