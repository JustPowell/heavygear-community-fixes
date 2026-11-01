# WASD control layout for Heavy Gear

Install: `python3 patcher/hg_controls.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear wasd`
Undo:    `python3 patcher/hg_controls.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear original`

| Key | Action |
|---|---|
| W / S | walk forward / backward (hold Shift to run) |
| A / D | turn legs left / right |
| Q / E | strafe left / right |
| Mouse | aim torso; left click fire, right click cycle weapon, middle click target what you aim at |
| Space | jump jets |
| C / Shift+C | crouch / stand up |
| R | skate (wheels) |
| F | turn legs to face where the torso is aiming |
| Tab | target nearest enemy |
| T / Shift+T | next / previous target |
| Y / Shift+Y | next / previous enemy |
| U / Shift+U | next / previous friendly |
| N / Shift+N | next / previous nav point |
| O | autopilot (was A) |
| V | cockpit view (was C) |
| Enter | cycle weapon |
| ; | fire weapon group, Shift+1/2/3 add weapon to group 1/2/3 |
| \ | toggle group fire |
| P | pick up / drop weapon |
| = / - | throttle up / down; 1-0 throttle presets (1 stop, 0 full) |
| Backspace or ` | reverse direction |
| , / . / / | torso left / right / centre |
| Z | zoom in (Shift+Z out, Ctrl+Z reset) |
| X / Shift+X | radar zoom in / out |
| I / L | infrared / enhanced vision |
| F1-F12, Esc | unchanged (comms menus, displays, main menu) |

The arrow keys still work as in the original layout (move/turn, Shift strafe, Ctrl look), and
keypad `/`, `*` and NumLock still fire weapon groups 1-3.

Using the game's own Controls screen and confirming changes rewrites `INPUTW.MAP`; run the
install command again afterwards. The install keeps the originals as `INPUTW.MAP.orig` and
`GAMEKEY.MAP.orig`.

## Printable card

[wasd-controls.pdf](wasd-controls.pdf) is this layout as a two-page card (keyboard, mouse,
install/undo) to print or keep open. `python3 mods/wasd/make_card.py` regenerates it; it needs pycairo (`python-cairo` on Arch,
`python3-cairo` on Debian/Ubuntu/Fedora). If you change the layout, update the table above and
the card's key labels together.
