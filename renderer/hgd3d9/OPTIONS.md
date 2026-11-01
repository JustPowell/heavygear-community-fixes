# hgd3d9 options

The plugin is installed as `PLUGIN\3dfx_hgd3d9.dll` (the game takes its hardware-renderer paths only when the plugin's file name contains
"3dfx" or "powervr"; see `docs/research/renderer-interface.md` section 9). Build and install with `renderer/hgd3d9/install.sh`.

Every option is an empty marker file in the game folder (the plugin's working directory); delete the file to turn it off. Nothing is needed for the
defaults.

## Known issue: no DXVK d3d9.dll in the game folder (Wine)
Under Wine, a native DXVK `d3d9.dll` in the game folder makes the cutscenes that follow a mission play as a blank dark-blue screen (audio only).
It does not matter which resolution, whether gamescope or its Vulkan layer is used, or whether the plugin unloads the DLL or draws into a child window; the
software renderer is fine, and so is the plugin on Wine's own Direct3D 9 (wined3d). Keep any `d3d9.dll` out of the game folder
(`mv d3d9.dll d3d9.dll.dxvk`); `run-heavygear.sh` warns when one is there. Window dumps and Wine traces showed identical window
state in working and blank movies, so the cause is in Wine's Vulkan state for the process, not something the plugin or the shell can undo.

## Output
Use `renderer/hgd3d9/res.sh` to switch resolution: `res.sh` (menu), `res.sh list`, `res.sh set 1600x1200` (or `4k`, `1080p`), `res.sh off`. It writes
`hgd3d9.res` (`WIDTHxHEIGHT`) into the game folder; the plugin reads it at start and sizes the game window to it (restart the game after a change). Any size from
320x240 to 7680x4320 is accepted; 4:3 sizes fill the window, anything wider gets side bars. `hgd3d9.res` wins over the marker files below.

With the `borderless` fix (`patcher/hgfix.py`) the game window is a borderless pop-up the size of the desktop, and the plugin leaves it that size.
Without `hgd3d9.res` the back buffer is the whole window and the picture is drawn at the window's largest 4:3 area (for example 1920x1440 on a
2560x1440 desktop), with black bars beside it. With `hgd3d9.res` the back buffer gets the window's shape, sized so the 4:3 picture in it has the asked size, and is scaled onto the window:
1280x960 on a 2560x1440 desktop renders at 1280x960 and shows in the centred 1920x1440 area.

| File | Effect |
|---|---|
| `hgd3d9.res960` `res1280` `res1440` `res1600` `res1920` `res2560` `res2880` | resize the game window to this client width at 4:3 (720, 960, 1080, 1200, 1440, 1920, 2160 high; 2880x2160 is the 4:3 equivalent of 4K); the render resolution is the window's. Without one of these the window keeps the size the game made. |
| `hgd3d9.res1920x1080` | a 16:9 window, to check the side bars: the 4:3 picture is centred, never stretched, and drawing is clipped to it. |
| `hgd3d9.vsync` | wait for vertical blank (off by default: the game's own limiter paces frames) |

The 2D layer (HUD) is a 640x480 picture drawn with point sampling, so it stays crisp at whole multiples (1280x960, 1920x1440) and slightly uneven at others.

## Picture
| File | Effect |
|---|---|
| `hgd3d9.nolights` | draw the game's flat ground glow instead of point lights; `lightrN`, `lightampN` (N * 0.25, default 4) scale the lights' radius and strength |
| `hgd3d9.glowtrue` | glows keep their true depth (and write it); `glowbiasN`, `glowpctN` bias them toward the camera |
| `hgd3d9.noblackkey`, `hgd3d9.arefN` (N * 16, default 1), `hgd3d9.nobleed`, `hgd3d9.bleedN` | transparency of keyed and alpha-palette sprites |
| `hgd3d9.dpassN` (N * 28, default 9) | alpha at which a sprite writes depth; 9 is off in effect |
| `hgd3d9.nosort`, `hgd3d9.opac5` | far-to-near sprite sorting off; sprite opacity |
| `hgd3d9.nativefills`, `hgd3d9.hidefar` | the native depth rules for opaque fills (whole gears show through hills) |
| `hgd3d9.nomips`, `hgd3d9.wquant` | mipmapping off; 16-bit W-buffer depth quantisation |

## Diagnostics (developers)
`hgd3d9.capture` records the plugin calls to `hgd3d9.cap` for offline replay, `hgd3d9.tee` runs our plugin beside the real 3Dfx plugin, `hgd3d9.dump`,
`hgd3d9.log`, `hgd3d9.timelapse`, `hgd3d9.window` (own window), `hgd3d9.p17modes`, `hgd3d9.skypainter`, `hgd3d9.sky2draw` and the
`odepth`, `obias`, `oslope`, `fillshift`, `skip` switches are experiments left in for the replay tooling. `renderer/hgd3d9/mode.sh live|tee|livecap|status`
switches between the common combinations. The log (`hgd3d9.log`) says `d3d9 lighting pass ready` when point lights are active and logs the
first failing Direct3D call otherwise.

## Game patch
`patcher/hgfix.py` fix `partdepth` (v1.2 only, opt-in) gives particle sprites their real depth; without it they have none and sort by the engine's order.
