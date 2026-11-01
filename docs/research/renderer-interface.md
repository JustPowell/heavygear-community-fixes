# Renderer plugin interface

How HGSHELL.DLL and HGSIM.DLL talk to the graphics drivers (`3DFXGEAR.DLL`, `DX5DRAW.DLL`,
`RENDDRAW.DLL`, `I76DRAW.DLL`). A replacement renderer (`renderer/hgd3d9`) is a DLL that exports
the same functions. Findings come from decompiling our own copy of the game and from runtime logs.

**Which build.** The game runs the v1.2 files (July 1998 `HG.EXE`, `HGSIM.DLL`, `HGSHELL.DLL`; April 1998 plugins).
Function addresses and `FUN_` names quoted in this document were first read in the *1997 disc build*, whose
plugin differs from 1.2 (for example `FirstDevice` is at `0x10001230` there and `0x10001350` in 1.2). Where the two differ
the 1.2 build is the reference, and a section says so. Runtime findings ([CMP]) are always from 1.2. Confidence tags:

- **[CODE]** read directly in the decompilation.
- **[CMP]** confirmed at runtime: an early logging stub plugin (since removed: hgd3d9 logs and captures the same calls) or the Glide
  logging proxy (`tools/glidelog/`) saw it in a real mission.
- **[INF]** inferred, not yet confirmed.
- **[?]** unknown.

Addresses are from the 3Dfx plugin unless noted. No game data is reproduced here, only counts
and layouts.

## 1. Loading and selection

Both HGSIM (`FUN_10036027`, `FUN_100361d8`, `FUN_1003650d`) and HGSHELL (`FUN_10039754`,
`FUN_100397ff`) have the same loader:

1. The shell scans `plugin\*.dll` (or, if `DLLFILE.INI` exists, reads the plugin names from it)
   and calls `LoadLibraryA` then `GetProcAddress("GetFuncDesc")` on each. [CODE]
2. `GetFuncDesc(char kind[256], int *id, char *name)` must write `"RASTER"` into `kind`
   (the loader compares it), set `*id` and, if `name` is non-null, write a display name. Returns 0. [CODE]
3. `CheckFunc(arg)` returns non-zero if the device can be used. The shell calls it once with `0`
   (or a saved setting). [CODE][CMP]
4. The shell accepts only **ids 0, 1 and 2** (`FUN_10039b14` rejects any other). Ids seen in the
   plugins: `I76DRAW` 0, `DX5DRAW` 1, `3DFXGEAR` 2, `RENDDRAW` 2. [CODE]
5. The chosen plugin's exports are bound into a table (HGSIM globals `0x109e3d24`-`0x109e3d64`,
   HGSHELL `0x102723a0`-`0x102723e4`) and the DLL stays loaded; the others are freed. [CODE]

How a plugin is picked [CMP]:

- The shell records the choice in `DLLFILE.INI` (the plugin file name) and `hgprm.cfg` (a switch:
  `/3dfx` for id 2, `/d3d` for id 1).
- A plugin that reports **id 2** and sits next to the originals is listed in the renderer menu under
  its own display name and is used when chosen. Nothing needs to be overwritten.
- A plugin that reports **id 1** was *not* used: the shell resolved id 1 to `dx5draw.dll`, which sorts
  first. A new renderer should therefore report id 2.

`GetNumDevice` was not called in our runs. [CMP]

**Where the choice is kept** (v1.2, Windows 11, 2026-10-31) [CMP]: the options screen's Graphics Type is saved as a
32-bit number at offset `0x58` of `hgsnd.cfg`, and at every mission start the shell writes `DLLFILE.INI` and the sim's
`/3dfx` option from it, so editing `DLLFILE.INI` alone does not last. `-1` is Software 640 (`I76DRAW`); otherwise it
is the position in the list of plugins it shows, which follows the order Windows lists `PLUGIN\*.dll` (by name,
ignoring case: `3DFXGEAR` before `3DFX_HGD3D9`). With `3dfx_hgd3d9`, `3dfxgear` (with a Glide driver), `i76draw` and
`renddraw` installed: 3Dfx `0`, Direct3D 9 renderer `1`, Software 640 `-1`. The app writes this number with
`DLLFILE.INI` (`windows/installer_core.py`, `select_graphics_type`). Not checked under Wine, whose directory order is
the Linux file system's.

## 2. Exports (19 names in the 3Dfx plugin)

All are looked up by name. A plugin may leave out ones the game never calls in that mode, but the
safe plan is to export every one.

**Calling convention: cdecl.** Every export in `3DFXGEAR.DLL` returns with a plain `ret`, never
`ret N`; a cdecl stub also ran for whole missions without trouble. [CODE][CMP]

| Export | Arguments | Notes |
|---|---|---|
| `GetFuncDesc` | `(char *kind, int *id, char *name)` | see section 1 |
| `CheckFunc` | `(arg)` | non-zero = usable |
| `GetNumDevice` | `()` | 3Dfx returns 1; not called in our runs [CMP] |
| `GetSocketCaps` | `()` | flag word: bit 0 = Z buffer, bit 1 = fog. Not called during a mission [CMP] |
| `SetLumaTable` | `()` | called once at start; 3Dfx: no-op [CODE][CMP] |
| `FirstDevice` | `(DeviceInfo *)` | open the display, see section 3 |
| `LastDevice` | `()` | free textures and close the display |
| `RenderRefresh` | `()` | called once per frame; 3Dfx only increments its frame counter, used for texture cache ageing [CODE][CMP] |
| `Render` | `(int prim, void *ctx, Vertex *v, int count, void *arg)` | see section 4 |
| `RenderNoClip` | same as `Render` | never called in a mission [CMP] |
| `SetState` | `(int state, int value)` | see section 5 |
| `SetTexturePalette` | `(int slot, void *palette)` | called as `(0, ptr)` at start and once more later; 3Dfx: no-op [CODE][CMP] |
| `LockDisplay` | `(u32 *pitch)` | returns the frame buffer pointer, see section 7 |
| `UnlockDisplay` | `()` | |
| `RefreshDisplay` | `()` | present the frame and clear the depth buffer (`grBufferSwap`, `grBufferClear`) [CODE] |
| `PreloadTexture` | `(Texture *)` | **never called**; textures are reached only through `Render` [CMP] |
| `UpdateTexture` | `(Texture *, int arg)` | never called in a mission [CMP] |
| `RestoreDevice` | `()` | re-open after the window lost the display; not seen (no Alt-Tab in the runs) [CODE] |
| `LostDeviceDisplay` | `()` | save state before the display is lost; not seen [CODE] |

The same names are exported by `DX5DRAW`, `RENDDRAW` (software) and `I76DRAW` (a partial
set), so those three are working references for behaviour the 3Dfx plugin only hints at.

## 3. `FirstDevice(DeviceInfo *)`

Observed block (32 words readable) from a real start-up, 3Dfx id [CMP]:

| Offset | Value seen | Meaning |
|---|---|---|
| `+0x00` | pointer | the same pointer is passed as the `ctx` argument of every `Render`; it points at `{1, 640, 480, 0, 0, 0, 639, 479}` (enable flag, width, height, three zeros, width-1, height-1) |
| `+0x04` | `8` | the 3Dfx plugin tests `== 8` to choose its palettised-texture path (`iRam1001f514` in 1.2) [CODE][CMP]. It is not the depth of the 2D layer, which is RGB565 (section 7) |
| `+0x08` | `3` or `2` | flags: bit 0 = depth buffer, bit 1 = fog [CODE]; bit 7 and bit 8 as in the code (see below). The value differed between runs |
| `+0x14` | `0x40775c4f`, `0x40000000` | read by the code as fog colour [CODE]; the values look like floats (2.0), so the meaning is unclear [?] |
| `+0x18`, `+0x1c` | `1.0f`, `500000.0f` | not read by the 3Dfx plugin; look like near and far depth limits [INF] |
| `+0x20` | `0` | not used by 3Dfx. `DX5DRAW` requires it non-zero (a device or window handle copied from the shell's record) and fails otherwise [CODE]. Not tested at runtime [?] |
| `+0x28` | `0x200` | a pointer or flag word, used by the 3Dfx plugin to create its texture list [CODE]; value `0x200` looks like a size [?] |
| `+0x3c`, `+0x40` | `640`, `480` | screen width and height [CODE][CMP] |
| `+0x44` onward | `0xffff`, ... | the tail looks unrelated to rendering (one run had a timestamp) [INF] |

Other bits read from `+0x08`: bit 7 = flag stored in the plugin; bit 8 = textures use a 16-bit-RGB palette conversion. [CODE]

`FirstDevice` returns 0 on success, 1 on failure. The 3Dfx plugin opens a 640x480 Glide window with
`grSstWinOpen(0,7,0,0,0,2,1)`; the width and height are only used for clip maths. [CODE]
The window handle given to Glide is 0, so a modern renderer has to create or find its own window. [CMP]

## 4. `Render(prim, ctx, verts, count, arg)`

- `ctx` is the block described in section 3. [CMP]
- `verts` points to `count` vertices of 9 dwords (36 bytes) each. [CODE][CMP]
- `arg` is a texture block for textured primitives (section 6); for primitive 12 the colour is at `arg+4`. [CODE]
  For primitive 15 it is not a texture (see below). [CMP]
- Return 0 when drawn, 1 when the primitive was clipped away entirely. [CODE]
  A stub that always returned 1 did not crash or stop the game; the return value is not checked strictly. [CMP]

Vertex layout [CODE unless marked]:

| Offset | Type | Meaning |
|---|---|---|
| 0 | float | screen x |
| 4 | float | screen y |
| 8 | float | `w`, the eye depth: `1 / (1/w)`. Seen: 78000 with `1/w` = 1.28e-5; the background fill has `w` ~ FLT_MAX [CMP] |
| 12 | float | `1/w` (0 for the background fill) [CMP] |
| 16 | uint32 | light intensity, an **integer** 0 to 255 (the dumps show `0x0000005f`; it is not a float), multiplied into the RGB bytes |
| 20, 21, 22 | uint8 x3 | colour R, G, B |
| 23 | uint8 | alpha (blended primitives) |
| 24 | uint32 | top byte is the alpha / fog value |
| 28 | float | u, a plain 0..1 fraction (not pre-multiplied by `1/w`) [CMP] |
| 32 | float | v, same |

Texture coordinates and position in the 1.2 plugin (`FUN_10002090`, the textured draw path) [CODE, 1.2]: Glide `s = u * scale * (1/w) * 255`
and `t = v * scale * (1/w) * 255`, where `scale` is 1.0 for square textures and 0.5, 0.25 or 0.125 for the non-square aspect ratios.
The disc build added half a texel (`128 / size`); 1.2 does not. Colour is `(channel * (int)light) >> 8`; alpha is the vertex alpha
byte when blending is on and `255 - (word6 >> 24)` when it is off. The plugin adds the float 786432.0 (a snap bias) to x and y
before calling Glide; a new renderer does not need it.

Primitive types (the first argument), with the 3Dfx plugin's handling. Names are guesses
from how each case behaves [INF]:

| `prim` | Handling |
|---|---|
| 0, 1, 2 | opaque textured polygon, texture at `arg` |
| 3, 4 | opaque textured polygon after switching blending off |
| 5, 6, 10, 11 | alpha-blended textured polygon (src alpha / one-minus-src alpha) |
| 7 | flat-shaded, untextured polygon |
| 8, 9 | untextured polygon with colour combine mode 1 |
| 12 | constant-colour polygon with a texture (colour from `arg+4`) |
| 13 | textured polygon, no blend |
| 14, 15 | blended variant of 13 |
| 16, 17 | polygon drawn with fog off, then fog back on |
| 18 (0x12) | another colour-combine variant |

**Primitives actually used in a mission** [CMP]: only 1, 2, 8, 15 and 18 were ever called. The
other 14 types never appeared, so a renderer can start with these five.

- Prims 1 and 2 are the bulk of the traffic: triangles and quads (counts 3 to 5 seen) with a texture.
- Prim 15, in the first frames, is two full-width fills at y = 0 and y = 240 (sky and ground halves). Its
  `arg` is a small parameter block, not a texture.
- Prim 8 appears later in a mission, in smaller numbers; prim 18 appears later still.

The 3Dfx plugin clips polygons to its rectangle itself (`FUN_10002db0`, a Sutherland-Hodgman style
clip against the four edges, interpolating colour, `1/w`, u and v) and draws the result as a fan. A new
renderer can skip this and let the GPU clip.

## 5. `SetState(state, value)`

The v1.2 3Dfx plugin (`SetState` at `0x10002b10` in the 1.2 build) implements these states [CODE, 1.2]:

| state | value | Effect |
|---|---|---|
| 1 | `0x200000` | fog on (`grFogMode(1)`); any other value = fog off |
| 5 | any | stored in a plugin variable (use unknown) |
| 7 | any | stored in a plugin variable, initial value 1 (use unknown) |
| 0xc | any | clear the depth buffer only: colour mask off, `grBufferClear`, colour mask on |
| 0xd | - | returns the total texture memory (the sum of `grTexMaxAddress` over the boards) |
| 0xe | 0 or not | depth buffer mode: 0 = off, anything else = W-buffer (`grDepthBufferMode(2)`) |

The disc (1.0) build only handled states 2 and 6; an earlier version of this document wrongly applied that to 1.2.

What the engine sends in a mission [CMP]: `(7, 0)` once at start, `(0xc, 1)` every frame, and state 1 with value `0x200000` (fog on) or `0` (fog off),
which changed during play (in one run `(1, 0)` first appeared at frame 256 and `(1, 0x200000)` at frame 302). In a later run the player pressed low-light mode twice and the log shows fog off at frame 645 and back on at 681, so fog
is dropped for low-light (night vision) and restored when it ends. So:

- fog is switched by state 1, not fixed;
- `(0xc, 1)` is a **depth clear**, and the log order shows it comes right after the two full-width fills (prim 15) and
  before the geometry. A renderer must support it, or the geometry will lose to the fills' depth.
- states 5, 0xd and 0xe were not seen in a mission; 0xd returns a value, so a stub that always returns 0 may report no texture memory.

Fog is also toggled per primitive by the plugin itself (`grFogMode` around some primitives). [CMP]

## 6. Textures

`arg` is a `Texture *` for textured primitives. Layout, from the code and from dumps of the real blocks:

- `*arg` is a pointer to a descriptor. The descriptor and the block often live together on the engine's stack. [CODE][CMP]
- Descriptor words [CMP]:

  | Word | Meaning |
  |---|---|
  | `desc[0]` | mip-level bitmask (bit `n` = a `2^n`-pixel level). Only the base level's bit was set in the clean samples: `0x100`, `0x80`, `0x40` for 256, 128 and 64 pixel textures |
  | `desc[1]` | a size word, equal to `desc[0]` in the samples. The 3Dfx cache uses it to find a slot of the same size class [CODE] |
  | `desc[2]` | pointer to the 8-bit pixel indices |
  | `desc[3]` | pointer to the palette: 32-bit entries `0x00RRGGBB` (top byte = transparency, 0xFF transparent), entry 0 is `0`. No leading count word in the samples. The pixels follow the palette in memory in the samples, so the entry count is inferred from the distance [INF] |
  | `desc[4]` | read as the colour-key index by the 3Dfx plugin [CODE], but the values seen (`0`, `0x100`, `0x7baeb044`) do not look like an index [?] |

- Textures are 8-bit palettised, up to 256x256, always square, with a mip chain that the Glide driver sees as levels
  `n` to 8 (down to 1x1) even though only the base level is declared in the mask. The plugin builds the smaller levels
  itself [INF] (`FUN_10004610` / `FUN_10004a60`). A new renderer should generate mips on the GPU.
- The cache key is the `Texture *` itself, not `desc[1]` (`FUN_100041b0(cache, tex, ...)`). [CODE]
- Textures are uploaded lazily from inside `Render`; there is no preload or update call. [CMP]
- When the palette changes (`SetTexturePalette` or a new palette pointer), the 3Dfx plugin re-sends it with `grTexDownloadTable`. [CODE]
- The colour-key path calls `grChromakeyMode(1)` and `grChromakeyValue(...)`. That is the cause of the black
  particle squares, which `tools/glidelog/` fixes by converting each keyed P_8 texture to alpha (alpha = 255 - the palette's top byte). [CODE][CMP]

A new renderer should convert each texture once to RGBA with alpha from the palette's top byte, and cache the result by `Texture *`.
Re-convert when the palette changes.

## 7. Frame order and the 2D layer

Per frame [CMP]: many `Render` calls, then `RenderRefresh`, then `LockDisplay` ... `UnlockDisplay`, then `RefreshDisplay`.
`FirstDevice` once, `SetTexturePalette` once at start.

`LockDisplay` [CODE, 1.2 machine code][CMP]:

- The 3Dfx plugin calls `grLfbLock(write only, back buffer, writeMode 0 = RGB565, origin 0, pixelPipeline 0, &info)`, then
  returns `info.lfbPtr` in EAX and writes `info.strideInBytes` through its argument; it returns 0 if the lock fails.
  The caller stores the pointer and `stride - 1`. The signature is `u32 LockDisplay(u32 *stride_bytes)`. (The decompiler
  shows the function with no argument; the disassembly shows `mov [ecx], edx` with the caller's pointer.)
- **The 2D layer is 16 bits per pixel, RGB565, written directly into the back buffer** after the 3D polygons are drawn.
  There is no palette. The first stub runs handed out an 8-bit buffer with pitch 640 and decoded the dump as 8-bit; read as
  RGB565 with 640-byte rows the same dump is a full-colour picture (an "Exiting Mission Area" dialog with metal window frames),
  so that earlier description (a palettised layer, an unknown display palette) was wrong. A correct 640x480 capture needs a
  stride of at least 1280 bytes.
- With `LockDisplay` returning 0 ("cannot lock"), only 9 `Render` calls came through in 261 frames; with a real buffer
  about 130 per frame flowed. The cause is probably the lock result, but the first run may also have been a loading screen [INF].
- Per frame the engine writes both in-mission HUD elements and full-screen 2D screens through this path. [CMP]

Open points for the new renderer:

- The engine writes only the pixels it needs on the real back buffer, which already holds the 3D picture. A new renderer can
  either hand out a persistent overlay cleared to 0 and treat 0 as "not drawn" (the likely rule, since 0x0000 is also the
  value of untouched pixels, so a deliberately black HUD pixel would be lost), or hand out a copy of the rendered frame and
  upload it back. This needs testing. [INF]

`LostDeviceDisplay` and `RestoreDevice` bracket display loss.

## 8. Workload in a mission (Glide level) [CMP]

One full mission, 3712 frames, seen at the Glide level by the logging proxy: about **974 polygons and 60 lines or points per
frame**, in a few classes. Polygon sizes: mostly 3 or 4 vertices, a few up to 9 or more.

| Class | Polygons per frame | Notes |
|---|---|---|
| Keyed P_8 sprites and particles: chroma key on, src-alpha blend, texture x constant colour, fog off | ~576 | the biggest load; always 4-vertex quads |
| Opaque lit world geometry: no key, blend off, texture x iterated light, fog on | ~290 | terrain, buildings, gears |
| Alpha-blended textured, no key | ~34 | |
| Opaque, fog off | ~27 | |
| RGB565 textured polygons plus anti-aliased lines | ~12 polygons, ~10 lines | probably vector HUD or radar elements [INF] |
| Native AP_88 keyed textures | ~5 | 64x64 |
| Untextured Gouraud | under 1 | |

Texture formats seen: P_8 (almost all), AP_88 and RGB565. Largest mip level 256, 128, 64 or 32 pixels.

The mapping from the plugin's `prim` numbers to these classes is not yet known. [?]

## Open questions

- How `prim` 1, 2, 8, 15 and 18 map to the Glide classes in section 8. A wrapper plugin that logs both sides would settle it. [?]
- What `SetState` states 5 and 7 are used for, and whether the engine ever sends 0xd or 0xe. [?]
- Where the colour-key index lives (`desc[4]` does not look like one) and how the palette length is stored. [?]
- The transparency rule for the 2D layer (section 7), now that it is known to be RGB565 with no palette. [?]
- `DeviceInfo` fields `+0x14`, `+0x18`, `+0x1c`, `+0x28`; and what `+0x20` holds under the Direct3D id. [?]
- How the "high resolution" (`/high`) mode changes the output; the stub only saw 640x480. [?]
- Whether `RenderNoClip` differs only by skipping the clip step; it was never called. [INF]

## 9. The sim decides the renderer class from the plugin's file name [CODE, found 2026-10-06]

HGSIM (v1.2) reads `dllfile.ini`, builds `plugin\<name>` for each line, loads it, calls `GetFuncDesc(kind, &id, 0)` (no name buffer) and, when the
plugin is accepted, copies that **path string** into the device record at +4. Later in the start-up function (`SimMain`, machine code at
0x1006ffb1) it upper-cases the string and searches it for `3DFX`, then `POWERVR`. A hit sets `iRam1014b954` = 1, the "hardware renderer" flag.
The sim tests that flag in dozens of places, together with the `/d3d` flag (`iRam1014a5e8`); when both are 0 it takes its software-renderer paths.

So the plugin's **file name** has to contain `3dfx` (or `powervr`), in any case, for the engine to treat it as a hardware renderer. `hgd3d9.dll`
did not match, so every capture made under that name shows the engine's software-mode stream: no alpha-palette (AP_88) particle textures and far
fewer keyed sprites (explosions, dust). Install the plugin as `3dfx_hgd3d9.dll` (`renderer/hgd3d9/install.sh`). The shell passes `/high /3dfx`
for any plugin it lists as a hardware device, which was already the case. (An earlier version of this note said the `GetFuncDesc` name was
searched; the disassembly shows it is the path.)
