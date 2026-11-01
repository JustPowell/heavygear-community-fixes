#!/usr/bin/env python3
"""
hg_controls.py - switch Heavy Gear between control layouts.

  hg_controls.py GAME_DIR wasd        install the WASD layout (mods/wasd/)
  hg_controls.py GAME_DIR original    put the game's own INPUTW.MAP / GAMEKEY.MAP back

Two files hold the bindings, both plain text in the game folder:
  INPUTW.MAP   movement, aiming, weapons, targeting   ("action { + keyboard KEY ... }")
  GAMEKEY.MAP  command keys: menus, F-key displays, throttle presets, autopilot ...
The first install keeps the originals as INPUTW.MAP.orig / GAMEKEY.MAP.orig, and the layout is
built from them (mods/<layout>/INPUTW.MAP.ed plus GAMEKEY_EDITS below). INPUTW.MAP.orig must be
the game's Action scheme file (the default setup-heavygear-wine.sh installs).

Note: confirming changes in the game's own Controls screen makes the shell rewrite
INPUTW.MAP from its profile (CURRENT.CCT); run this again afterwards to get WASD back.
"""
import os, re, shutil, stat, sys

FILES = ('INPUTW.MAP', 'GAMEKEY.MAP')

# GAMEKEY.MAP for a layout is the game's own file with a few keys moved (the game's copy
# isn't redistributed here). (command, new key) pairs per layout:
GAMEKEY_EDITS = {
    'wasd': [('TOGGLE_AUTOPILOT', 'o'), ('COCKPIT_VIEW', 'v')],   # a and c are taken by WASD
}

def apply_ed_script(src, script, dst):
    """Apply a `diff -e` script (a/c/d commands, highest line first) to src, write dst with CRLF.
    An ed script carries only the new lines, so the game's own file isn't copied into this repo."""
    with open(src, 'rb') as source:
        lines = source.read().decode('latin-1').replace('\r\n', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    with open(script, encoding='latin-1') as script_file:
        cmds = script_file.read().split('\n')
    i = 0
    while i < len(cmds):
        m = re.fullmatch(r'(\d+)(?:,(\d+))?([acd])', cmds[i])
        i += 1
        if not m:
            if cmds[i - 1].strip():
                sys.exit(f'{script}: bad command {cmds[i - 1]!r}')
            continue
        a = int(m.group(1)); b = int(m.group(2) or a); op = m.group(3)
        new = []
        if op in 'ac':
            while cmds[i] != '.':
                new.append(cmds[i]); i += 1
            i += 1
        if op == 'a':
            lines[a:a] = new
        else:
            lines[a - 1:b] = new
    with open(dst, 'wb') as output:
        output.write(('\r\n'.join(lines) + '\r\n').encode('latin-1'))

def edit_gamekey(src, dst, layout):
    """Copy src to dst with the layout's key changes (keeps the file's CRLF line endings)."""
    with open(src, 'rb') as source:
        data = source.read().decode('latin-1')
    for cmd, key in GAMEKEY_EDITS[layout]:
        data, n = re.subn(r'(?m)^(%s[ \t]+)\S+' % cmd, lambda m: m.group(1) + key, data)
        if n == 0:
            sys.exit(f'{src}: no {cmd} line - unexpected GAMEKEY.MAP')
    with open(dst, 'wb') as output:
        output.write(data.encode('latin-1'))

def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2 or arguments[1] not in ('wasd', 'original'):
        sys.exit(__doc__)
    game, layout = arguments
    # mods/ sits next to patcher/ in the repo; a PyInstaller .exe carries it inside (sys._MEIPASS)
    mods = os.path.join(getattr(sys, '_MEIPASS', ''), 'mods') if hasattr(sys, '_MEIPASS') else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mods')
    for f in FILES:
        dst = os.path.join(game, f)
        if not os.path.exists(dst):
            sys.exit(f'{dst} not found - is {game} the Heavy Gear folder?')
        if not os.path.exists(dst + '.orig'):
            shutil.copy2(dst, dst + '.orig')
        os.chmod(dst, os.stat(dst).st_mode | stat.S_IWRITE)
        if layout == 'original':
            shutil.copyfile(dst + '.orig', dst)
        elif f == 'GAMEKEY.MAP':
            edit_gamekey(dst + '.orig', dst, layout)
        else:
            apply_ed_script(dst + '.orig', os.path.join(mods, layout, f + '.ed'), dst)
        print(f'{f}: {layout}')

if __name__ == '__main__':
    main()
