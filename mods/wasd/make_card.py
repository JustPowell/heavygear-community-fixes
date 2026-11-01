#!/usr/bin/env python3
"""Print-ready reference card for the WASD layout (mods/wasd/).

  python3 mods/wasd/make_card.py [OUT.pdf]    default: wasd-controls.pdf next to this script (committed)

Needs pycairo (python-cairo / python3-cairo in most distributions). The key labels below are
typed by hand from the table in this folder's README.md; keep the two in step when the layout changes.
"""
import cairo, math, sys
from pathlib import Path

OUT = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent / "wasd-controls.pdf")
Path(OUT).parent.mkdir(parents=True, exist_ok=True)
W, H = 792, 612  # US Letter landscape
FONT = "DejaVu Sans Condensed"

GROUPS = {  # key: (name, badge, fill rgb, hatch)
    "M": ("Movement", "Mv", (0.80, 0.89, 0.97), "none"),
    "A": ("Aiming / weapons", "Ai", (0.98, 0.85, 0.68), "diag"),
    "T": ("Targeting", "Tg", (0.80, 0.92, 0.77), "cross"),
    "V": ("Views / sensors", "Vw", (0.88, 0.83, 0.94), "dots"),
    "H": ("Throttle / direction", "Th", (0.97, 0.93, 0.69), "horiz"),
    "U": ("Unchanged (original)", "", (0.90, 0.90, 0.90), "none"),
    "-": ("Modifier", "", (1, 1, 1), "none"),
    "x": ("Not bound", "", (1, 1, 1), "none"),
}

surf = cairo.PDFSurface(OUT, W, H)
surf.set_metadata(cairo.PDF_METADATA_TITLE, "Heavy Gear - WASD controls")
c = cairo.Context(surf)


def font(size, bold=False, mono=False):
    face = "DejaVu Sans Mono" if mono else FONT
    c.select_font_face(face, cairo.FONT_SLANT_NORMAL,
                       cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    c.set_font_size(size)


def text(x, y, s, size=8, bold=False, align="l", mono=False, rgb=(0, 0, 0)):
    font(size, bold, mono)
    c.set_source_rgb(*rgb)
    ext = c.text_extents(s)
    if align == "c":
        x -= ext.x_advance / 2
    elif align == "r":
        x -= ext.x_advance
    c.move_to(x, y)
    c.show_text(s)
    return ext.x_advance


def width(s, size, bold=False, mono=False):
    font(size, bold, mono)
    return c.text_extents(s).x_advance


def rrect(x, y, w, h, r=3):
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    c.close_path()


def hatch(x, y, w, h, kind, r=3):
    if kind == "none":
        return
    c.save()
    rrect(x, y, w, h, r)
    c.clip()
    c.set_source_rgb(0.45, 0.45, 0.45)
    c.set_line_width(0.45)
    step = 5
    if kind in ("diag", "cross"):
        t = -h
        while t < w:
            c.move_to(x + t, y + h)
            c.line_to(x + t + h, y)
            t += step
        c.stroke()
    if kind == "cross":
        t = 0
        while t < w + h:
            c.move_to(x + t, y + h)
            c.line_to(x + t - h, y)
            t += step
        c.stroke()
    if kind == "horiz":
        t = 3
        while t < h:
            c.move_to(x, y + t)
            c.line_to(x + w, y + t)
            t += step
        c.stroke()
    if kind == "dots":
        yy = y + 3
        row = 0
        while yy < y + h:
            xx = x + 3 + (2.5 if row % 2 else 0)
            while xx < x + w:
                c.arc(xx, yy, 0.55, 0, 2 * math.pi)
                c.fill()
                xx += 5
            yy += 5
            row += 1
    c.restore()


overflow = []


def key(x, y, w, h, cap, label="", shift="", ctrl="", grp="x", fsz=6.3):
    name, badge, fill, pat = GROUPS[grp]
    c.set_source_rgb(*fill)
    rrect(x, y, w, h)
    c.fill()
    hatch(x, y, w, h, pat)
    c.set_source_rgb(0, 0, 0)
    c.set_line_width(0.9 if grp not in ("x",) else 0.5)
    if grp == "x":
        c.set_source_rgb(0.6, 0.6, 0.6)
    rrect(x, y, w, h)
    c.stroke()
    # keycap name, top-left, on a small white tab so hatching never touches it
    capcol = (0.55, 0.55, 0.55) if grp == "x" else (0, 0, 0)
    csz = 8 if len(cap) <= 2 else 6.5
    cw = width(cap, csz, True)
    if grp != "x":
        c.set_source_rgb(1, 1, 1)
        c.rectangle(x + 1.5, y + 1.5, cw + 3, csz + 1.5)
        c.fill()
    text(x + 3, y + csz + 1.5, cap, csz, True, rgb=capcol)
    if badge:
        bw = width(badge, 5.2, True) + 3
        c.set_source_rgb(0, 0, 0)
        rrect(x + w - bw - 2, y + 2, bw, 7, 1.5)
        c.fill()
        text(x + w - bw / 2 - 2, y + 7.4, badge, 5.2, True, "c", rgb=(1, 1, 1))
    # label lines on a white plate
    lines = []
    for s in label.split("\n") if label else []:
        lines.append((s, False))
    if shift:
        for j, s in enumerate(shift.split("\n")):
            lines.append(("⇧ " + s if j == 0 else s, True))
    if ctrl:
        lines.append(("Ctrl " + ctrl, True))
    if not lines:
        return
    lh = fsz + 1.4
    total = lh * len(lines)
    maxw = max(width(s, fsz, bold=not sh) for s, sh in lines)
    if maxw > w - 4:
        overflow.append((cap, label, maxw, w))
    top = y + h - 2 - total
    px = x + (w - maxw) / 2 - 1.5
    c.set_source_rgb(1, 1, 1)
    rrect(px, top - 0.5, maxw + 3, total + 1, 1.5)
    c.fill()
    yy = top + fsz
    for s, sh in lines:
        text(x + w / 2, yy, s, fsz, bold=not sh, align="c")
        yy += lh


def page_title(sub):
    text(28, 40, "Heavy Gear — WASD controls", 24, True)
    text(W - 28, 40, sub, 9, False, "r", rgb=(0.3, 0.3, 0.3))
    c.set_source_rgb(0, 0, 0)
    c.set_line_width(1.5)
    c.move_to(28, 48)
    c.line_to(W - 28, 48)
    c.stroke()


# ----------------------------------------------------------------- page 1
page_title("Keyboard + mouse layout · install with patcher/hg_controls.py")

U = 48.5
KH = 44.5
X0 = 28
Y0 = 62


def K(col, row, w=1, *a, **k):
    key(X0 + col * U + 1, Y0 + row * (U) + 1 + (10 if row > 0 else 0), w * U - 2, KH, *a, **k)


# Row 0: Esc + F-keys (unchanged)
K(0, 0, 1, "Esc", "Main\nmenu", grp="U")
fl = ["Mission\ncomms", "Squad 1", "Squad 2", "Squad 3", "Squad 4", "Squad 5", "Squad 6",
      "Radar\nmap", "Target\ndisplay", "Ordnance\nview", "HUD\non/off", "Objec-\ntives"]
fx = [2, 3, 4, 5, 6.5, 7.5, 8.5, 9.5, 11, 12, 13, 14]
for i, (xx, lb) in enumerate(zip(fx, fl)):
    K(xx, 0, 1, f"F{i + 1}", lb, grp="U")

# Row 1: number row
K(0, 1, 1, "`", "Reverse", grp="H")
nums = {1: ("Stop", "Grp 1 +"), 2: ("Thr 2", "Grp 2 +"), 3: ("Thr 3", "Grp 3 +"),
        4: ("Thr 4", ""), 5: ("Thr 5", ""), 6: ("Thr 6", ""), 7: ("Thr 7", ""),
        8: ("Thr 8", ""), 9: ("Thr 9", ""), 0: ("Full", "")}
for i, d in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 0]):
    lb, sh = nums[d]
    K(1 + i, 1, 1, str(d), lb, sh, grp="H")
K(11, 1, 1, "-", "Thr\ndown", grp="H")
K(12, 1, 1, "=", "Thr\nup", grp="H")
K(13, 1, 2, "Backspace", "Reverse", grp="H")

# Row 2
K(0, 2, 1.5, "Tab", "Target\nnearest", grp="T")
r2 = [("Q", "Strafe L", "", "M"), ("W", "Walk fwd", "Run", "M"), ("E", "Strafe R", "", "M"),
      ("R", "Skate", "", "M"), ("T", "Next\ntarget", "Prev", "T"),
      ("Y", "Next\nenemy", "Prev", "T"), ("U", "Next\nfriend", "Prev", "T"),
      ("I", "Infrared", "", "V"), ("O", "Auto-\npilot", "", "V"),
      ("P", "Pick up/\ndrop wpn", "", "A"), ("[", "", "", "x"), ("]", "", "", "x")]
for i, (cp, lb, sh, g) in enumerate(r2):
    K(1.5 + i, 2, 1, cp, lb, sh, grp=g)
K(13.5, 2, 1.5, "\\", "Toggle\ngroup fire", grp="A")

# Row 3
K(0, 3, 1.75, "Caps", "", grp="x")
r3 = [("A", "Turn legs\nleft", "", "M"), ("S", "Walk back", "Run", "M"),
      ("D", "Turn legs\nright", "", "M"), ("F", "Legs to\ntorso", "", "M"),
      ("G", "", "", "x"), ("H", "", "", "x"), ("J", "", "", "x"), ("K", "", "", "x"),
      ("L", "Enhanced\nvision", "", "V"), (";", "Fire\ngroup", "", "A"), ("'", "", "", "x")]
for i, (cp, lb, sh, g) in enumerate(r3):
    K(1.75 + i, 3, 1, cp, lb, sh, grp=g)
K(12.75, 3, 2.25, "Enter", "Cycle weapon", grp="A")

# Row 4
K(0, 4, 2.25, "Shift", "hold: run / modifier", grp="-")
r4 = [("Z", "Zoom +", "Zoom −", "V"), ("X", "Radar\nzoom +", "Radar −", "V"),
      ("C", "Crouch", "Stand up", "M"), ("V", "Cockpit\nview", "", "V"),
      ("B", "", "", "x"), ("N", "Next nav", "Prev", "T"), ("M", "", "", "x"),
      (",", "Torso\nleft", "", "A"), (".", "Torso\nright", "", "A"), ("/", "Torso\ncentre", "", "A")]
for i, (cp, lb, sh, g) in enumerate(r4):
    K(2.25 + i, 4, 1, cp, lb, sh, ctrl=("reset" if cp == "Z" else ""), grp=g)
K(12.25, 4, 2.75, "Shift", "", grp="-")

# Row 5
K(0, 5, 2, "Ctrl", "", grp="-")
K(2, 5, 1.5, "Alt", "", grp="x")
K(3.5, 5, 7.5, "Space", "Jump jets", grp="M", fsz=8)
K(11, 5, 1.5, "Alt", "", grp="x")
K(12.5, 5, 2.5, "Ctrl", "", grp="-")

# Legend
ly = Y0 + 6 * U + 18
text(X0, ly + 2, "KEY GROUPS", 8, True)
lx = X0 + 70
for g in ["M", "A", "T", "V", "H", "U", "x"]:
    name, badge, fill, pat = GROUPS[g]
    c.set_source_rgb(*fill)
    rrect(lx, ly - 8, 22, 14)
    c.fill()
    hatch(lx, ly - 8, 22, 14, pat)
    c.set_source_rgb(0.4, 0.4, 0.4) if g == "x" else c.set_source_rgb(0, 0, 0)
    c.set_line_width(0.8)
    rrect(lx, ly - 8, 22, 14)
    c.stroke()
    if badge:
        bw = width(badge, 5.2, True) + 3
        c.set_source_rgb(0, 0, 0)
        rrect(lx + 22 - bw - 1, ly - 7, bw, 7, 1.5)
        c.fill()
        text(lx + 22 - bw / 2 - 1, ly - 1.6, badge, 5.2, True, "c", rgb=(1, 1, 1))
    lab = name
    text(lx + 27, ly + 2, lab, 7.5)
    lx += 27 + width(lab, 7.5) + 14

# notes below legend
ny = ly + 26
notes = [
    "⇧ line on a key = what it does with Shift held.   “Thr 2” = throttle preset 2.   Ctrl+Z = reset zoom.   "
    "Keypad / and * with NumLock fire groups 1–3 as before.",
    "Arrow keys keep the original layout: Up/Down move, Left/Right turn legs, Shift+Left/Right strafe, Ctrl+arrows look.",
    "Esc and F1–F12 are unchanged (grey keys). Autopilot moved A → O and cockpit view C → V to free those keys.",
]
for i, n in enumerate(notes):
    text(X0, ny + i * 12, n, 7.6)
surf.show_page()

# ----------------------------------------------------------------- page 2
page_title("Mouse, install and undo")

# mouse drawing
mx, my, mw, mh = 60, 90, 130, 190
c.set_source_rgb(0.95, 0.95, 0.95)
rrect(mx, my, mw, mh, 55)
c.fill()
c.set_source_rgb(0, 0, 0)
c.set_line_width(1.5)
rrect(mx, my, mw, mh, 55)
c.stroke()
bh = 80
c.set_line_width(1)
c.move_to(mx, my + bh)
c.line_to(mx + mw, my + bh)
c.stroke()
c.move_to(mx + mw / 2 - 11, my)
c.line_to(mx + mw / 2 - 11, my + bh)
c.move_to(mx + mw / 2 + 11, my)
c.line_to(mx + mw / 2 + 11, my + bh)
c.stroke()
# middle wheel (targeting, crosshatch)
c.set_source_rgb(*GROUPS["T"][2])
rrect(mx + mw / 2 - 11, my + 12, 22, 40, 8)
c.fill()
hatch(mx + mw / 2 - 11, my + 12, 22, 40, "cross", 8)
c.set_source_rgb(0, 0, 0)
rrect(mx + mw / 2 - 11, my + 12, 22, 40, 8)
c.stroke()
# left/right fill with weapons colour
for bx in (mx + 6, mx + mw / 2 + 15):
    c.set_source_rgb(*GROUPS["A"][2])
    rrect(bx, my + 6, mw / 2 - 21, 68, 12)
    c.fill()
    hatch(bx, my + 6, mw / 2 - 21, 68, "diag", 12)
    c.set_source_rgb(0, 0, 0)
    rrect(bx, my + 6, mw / 2 - 21, 68, 12)
    c.stroke()
text(mx + 6 + (mw / 2 - 21) / 2, my + 44, "L", 12, True, "c")
text(mx + mw / 2 + 15 + (mw / 2 - 21) / 2, my + 44, "R", 12, True, "c")
text(mx + mw / 2, my + 36, "M", 10, True, "c")
text(mx + mw / 2, my + 140, "move = aim", 10, True, "c")
text(mx + mw / 2, my + 153, "torso pan / tilt", 8, False, "c")

# callouts
lines = [
    ("Left click", "fire weapon"),
    ("Right click", "cycle weapon"),
    ("Middle click", "target what you aim at"),
    ("Mouse move", "aim torso left/right and up/down"),
]
cx = 230
text(cx, 104, "MOUSE", 11, True)
for i, (a, b) in enumerate(lines):
    yy = 126 + i * 24
    text(cx, yy, a, 10, True)
    text(cx + 80, yy, b, 10)
text(cx, 126 + 4 * 24 + 4, "Torso aim is independent of the legs: use A/D to turn the legs, F to snap them to the torso.", 8,
     rgb=(0.2, 0.2, 0.2))

# right column: quick modifier summary
qx = 500
text(qx, 104, "SHIFT / CTRL AT A GLANCE", 11, True)
quick = [
    ("Shift + W / S", "run instead of walk"),
    ("Shift + C", "stand up (C alone crouches)"),
    ("Shift + T / Y / U / N", "previous target/enemy/friend/nav"),
    ("Shift + Z / X", "zoom out / radar zoom out"),
    ("Shift + 1 / 2 / 3", "add weapon to group 1 / 2 / 3"),
    ("Ctrl + Z", "reset zoom"),
]
for i, (a, b) in enumerate(quick):
    text(qx, 126 + i * 15, a, 8.6, True)
    text(qx + 112, 126 + i * 15, b, 8.6)

# arrows + unchanged
by = 310
text(28, by, "UNCHANGED", 11, True)
text(28, by + 18, "Arrow keys: original layout (Up/Down move, Left/Right turn legs, Shift+Left/Right strafe, Ctrl+arrows look).", 9)
text(28, by + 33, "F1–F12 and Esc: unchanged (comms menus, displays, main menu).", 9)
text(28, by + 48, "Keypad / and * with NumLock still fire weapon groups 1–3.", 9)

# install box
iy = 395
text(28, iy, "INSTALL / UNDO", 11, True)
c.set_source_rgb(0.95, 0.95, 0.95)
c.rectangle(28, iy + 8, W - 56, 62)
c.fill()
c.set_source_rgb(0, 0, 0)
c.set_line_width(0.8)
c.rectangle(28, iy + 8, W - 56, 62)
c.stroke()
text(38, iy + 25, "Install WASD:", 8.6, True)
text(38, iy + 38, "python3 patcher/hg_controls.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear wasd", 8.6, mono=True)
text(38, iy + 54, "Undo (restore original):", 8.6, True)
text(38, iy + 66, "python3 patcher/hg_controls.py ~/Games/HeavyGear/prefix/drive_c/HeavyGear original", 8.6, mono=True)
text(28, iy + 90, "Open the game’s own Controls screen and confirm changes and it rewrites INPUTW.MAP: run the install command again afterwards.", 8.6)
text(28, iy + 104, "Replace the path with your own Heavy Gear folder if it differs. Changes touch INPUTW.MAP and GAMEKEY.MAP; originals are kept as .orig.", 8.6)

surf.finish()
for o in overflow:
    print("OVERFLOW", o)
