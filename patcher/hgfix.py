#!/usr/bin/env python3
"""
hgfix.py - fixes for Heavy Gear (1997) on modern PCs, under Wine (Linux) or on Windows.
Supports the v1.0 (disc) and v1.2 (official patch) binaries; the version is detected from
the code itself, and anything else is refused without changes.

Fixes, by name (--fix / --skip), and where each is applied by default (--platform):
  limiter   1. frame limiter for menus and missions                 wine, windows
  display   2+4. 256-colour mode kept after missions (debrief) and
            desktop mode put back before movies (intro)            wine only
  palette   re-send the shell palette once after HGSHELL loads      off unless asked for
  dx5draw   set PLUGIN/DX5DRAW.DLL aside (no red menus after a mission
            on Windows; the game's own Direct3D renderer is gone)    windows
  anet2     3. no ANET2.DLL unload before missions (v1.2 freeze)   wine, windows
  nodisc    7. no disc 2 needed: cutscenes come from GAME_DIR/VIDEO    off unless asked for
  music     8. soundtrack from GAME_DIR/MUSIC/TRACKnn files (implies nodisc)    off unless asked for
  movie32   9. movie screens in 32-bit colour (no crash around movies)  windows
  moviebg  10. movie backdrop kept hidden (movies show without a
            Wine virtual desktop: high-resolution Direct3D 9 renderer)      wine only
  glide     5. 3Dfx particle colour key (retired: use the tools/glidelog
            proxy via linux/setup-glide.sh instead)                  off unless asked for
  borderless 11. menus and movies in one borderless window, scaled
            (v1.2; replaces display, moviebg, movie32)         on for v1.2, both platforms
"display" works around how Wine's DirectDraw handles mode changes. It is never applied on Windows (a request for
it there is ignored with a note): Windows' DirectDraw does not have that problem, and the hooks it adds are not
wanted there.

1. Frame limiter (HGSHELL.DLL and HGSIM.DLL)
   The shell's menu loops and the sim's main loop step animations once per frame with no
   timing; on a modern PC they run hundreds of frames a second and everything races.
   (The sim's own "-F=<fps>" limiter waits on a tick counter that never advances inside the
   wait loop in this Windows build, so it can't be used.)
   The once-per-frame functions are routed through a small limiter that waits until
   timeGetTime() crosses the next 1000/FPS ms boundary:
       HGSHELL.DLL  menu input pump  (v1.0 FUN_1002fc44, v1.2 FUN_100305ce)
       HGSIM.DLL    game-clock step  (v1.0 FUN_1002a983 via its jump stub 0x100025ae,
                                      v1.2 FUN_1001ff23 via its only call at 0x10070d0e)

2. Display-mode fix (HGSHELL.DLL)
   After a mission the screen can come back in 32-bit colour while the shell's DirectDraw
   surfaces are 8-bit; its lost-surface handler (FUN_10179df0) then calls Restore() forever
   and fails: black screen with the debrief audio playing. The patch counts consecutive failed
   Restore() calls on the primary surface; after MODEFIX_AFTER failures in a row it calls
   IDirectDraw::SetDisplayMode(width, height, 8) and retries; when that works it also tells
   the shell to re-send its palette (as on regaining focus), since the mode switch drops it. A few failures are normal and
   left alone - e.g. just before the intro movie, which then rebuilds DirectDraw in 16-bit.

3. Multiplayer-library unload fix (HG.EXE, v1.2 only)
   Before each single-player mission HG.EXE unloads ANET2.DLL in a loop
   (do FreeLibrary(h) while it succeeds). The patched (packed) 1.2 ANET2.DLL waits for one of
   its threads while unloading, and under Wine that thread can't exit while the loader lock is
   held: the game freezes on a black screen when a mission starts. The patch skips the unload
   (ANET2 stays loaded, exactly as it already does for network games); 3 bytes at 0x401339
   "push eax; call edi" -> "xor eax,eax; nop".

4. 256-colour mode kept across window activation (HGSHELL.DLL) - the real debrief fix
   Under Wine, DirectDraw's SetCooperativeLevel records the display mode current at that
   moment and re-applies it whenever the window is (re)activated. The shell calls it before
   switching to 640x480x8, so the recorded mode is the 32-bit desktop; when the window gets
   activated just after the shell starts (after every mission), Wine switches back to 32-bit,
   all 8-bit surfaces are lost, and what the debrief drew once (its background) is gone.
   The patch calls SetCooperativeLevel again, with the shell's own window and flags, right
   after SetDisplayMode(w, h, 8) succeeds, so Wine records the 8-bit mode instead. Only the
   8-bit branch, and the shell restores the desktop mode right before it builds a movie player
   (FilterGraph): DirectShow set up under 640x480x8 never draws a frame (black intro). Fix 2 remains as
   a fallback.
   Before that SetCooperativeLevel it calls SetDisplayMode(w, h, 8) a second time. After a movie the
   window is activated again in the middle of the shell's own SetDisplayMode, and Wine re-applies the
   mode it recorded (the desktop, restored for the movie) at once; the second call undoes that before
   the mode is recorded. In a 640x480 Wine virtual desktop the desktop mode has the shell's size and
   this went unnoticed; with Wine's emulated display modes (EmulateModeset, used for the
   high-resolution Direct3D 9 renderer) the menu came back drawn 640x480 in the corner of a full-size window.

5. 3Dfx particle transparency (PLUGIN/3DFXGEAR.DLL, v1.0 and v1.2)
   Particles are cut out with Glide colour-keying, key = the texture's palette entry for its key
   index. The plugin only sent grChromakeyValue when keying switched on, and the key keeps the
   palette entry's top byte; real Voodoo hardware ignores that byte, the Glide wrappers don't,
   and 1.2's particle palettes carry alpha there. Now every keyed texture sends its own key with
   the top byte cleared (small routine in the unused tail of .text).

   (Not applied: field +4 of the renderer start-up block - HGSIM.DLL v1.2)
   The sim passes the renderer a start-up block whose field +4 is hard-coded to 8, which makes
   PLUGIN/3DFXGEAR.DLL upload every texture as 8-bit palette (GR_TEXFMT_P_8, no alpha). Particles
   are drawn with alpha taken from the texture, so they come out as solid squares on black. When
   the device is 3Dfx/PowerVR (the sim's own 0x1014b954) the field is now 16, so the plugin uses
   its 16-bit textures (ARGB_1555, with a transparency bit) - "16-bit textures with alpha
   blending" as the 1.1 notes describe for 4 MB cards. Direct3D is left as it was.

6. Particle depth (HGSIM.DLL v1.2 only, on by default for v1.2: --skip partdepth)
   The sim draws every particle sprite (explosions, smoke, dust, sparks) as a quad whose four vertices live in the particle's object (FUN_10078c29). Their
   depth words w and 1/w are set to 1.0 when the particle is created and never updated, so each sprite is "at the camera": a renderer with a depth buffer
   cannot hide it behind a hill, and a far gear's dust shows through the terrain in front of it. The projection that places the sprite already leaves the
   camera-space depth next to its screen position; the patch stores that depth (scaled nearer by the sprite's screen radius, 0.2% per pixel, at most 50%,
   so a fireball centred on the ground is not cut in half by it) into the four vertices just before the draw call. The sim's own draw helper turns w into 1/w.
   This changes what any renderer sees (3Dfx included), and it needs a renderer that depth-tests the sprites.

7. No disc needed (HGSHELL.DLL and HGSIM.DLL; off unless asked for: --fix nodisc)
   The game looks for the first CD-ROM drive (GetLogicalDriveStringsA, then GetDriveTypeA == 5). The sim then
   wants "X:/video/B51MOVIE.AVI" on it, and the shell builds "X:/video/" as the folder its movie players read
   cutscenes from (backslashes in the game). Nothing else on the disc is read; the soundtrack is CD audio and
   is not covered. The patch:
       "cmp eax,5" after each GetDriveTypeA   ->  "cmp eax,eax", so the first drive in the list counts
       shell: the call to GetLogicalDriveStringsA in each scan goes to a 25-byte routine (section .nodisc) that
              answers with one drive, "./" (the game folder). It matters because some scans keep the drive string
              itself as the root their movie player uses, not only the "X:/video/" prefix they build; with a real
              drive such as C:/ those players look in the wrong place and the game crashes after the intro.
       shell format "%c:/%s/"                 ->  "./%.*s/"   (the drive letter, here '.', is a harmless precision)
       sim probe " :/video/B51MOVIE.AVI"      ->  " /../video/B51MOVIE.AVI"   (the drive letter replaces
                                                  the space, and "X/.." cancels out when the path is normalised)
   So the game reads video/ in its working folder, which is the game folder.
   All four of the shell's scans are patched. The last one returns only the drive letter, and its caller joins
   letter + ":/" + folder name + "/" for the object that plays the movies shown AFTER a mission; that ":/" becomes
   "/" so the result is "./video/" as well. (It was left out at first as "a run-from-disc layout": the movie before
   a mission then played and the one after it did not.)
   GAME_DIR/VIDEO must hold a copy of disc 2's VIDEO folder; --disc2 DIR copies it.

8. Soundtrack without the CD (HGSIM.DLL; off unless asked for: --fix music, which also turns on nodisc)
   HGSIM plays the music through MCI's "cdaudio" device and sets its volume through the aux API, both in WINMM.dll.
   The patch changes the name of HGSIM's WINMM import to "hgcd.dll" (in place, 9 bytes: "WINMM.dll" -> "hgcd.dll");
   that is the proxy built from tools/cdaudio, which forwards the rest of WINMM and, when GAME_DIR/MUSIC holds
   TRACKnn.wav/.mp3/... files (nn = the track number on the original disc), plays them as that disc's tracks.
   With no such files the proxy passes everything to the real WINMM, so a real disc still works.
   hgcd.dll must be in GAME_DIR (copied from --hgcd, or found next to this script or in tools/cdaudio) or the
   fix is refused: the game would not start without it. --music-from DIR copies the track files into GAME_DIR/MUSIC.

9. Movie screens in 32-bit colour (HGSHELL.DLL; on by default on Windows: --fix movie32)
   For a full-screen movie the shell sets up DirectDraw again in 640x480x16 and lets DirectShow play the file in a
   window on top. On Windows 8 and later 8- and 16-bit modes are emulated by the DWM8And16BitMitigation compatibility
   layer (apphelp.dll), which keeps ONE record of "the primary surface" for the whole process. DirectShow's video
   renderer probes DirectDraw each time its pin is connected (and it reconnects when the display mode changes): it
   makes its own DirectDraw object, creates a primary surface and releases both. While a 16-bit mode is emulated the
   layer takes that primary as the new one: it releases the surfaces it holds for the shell's primary, and when the
   probe's DirectDraw object goes away its record points at surfaces that no longer exist. The shell's next
   RestoreDisplayMode makes the layer release them again: access violations inside apphelp.dll that it usually
   swallows, and now and then a crash (in apphelp.dll, or later in ntdll's heap code). Whether the probe lands before
   or after the shell has its primary is a matter of timing, so it comes and goes: after the intro, after a
   briefing movie, after the movie that follows a mission.
   The patch changes the bits-per-pixel argument of that SetDisplayMode call from 16 to 32 ("push 10h" -> "push 20h").
   A 32-bit mode is not emulated, the layer keeps no record for it, and the probe is harmless. The movie itself is
   drawn by DirectShow in its own window, so the shell's surfaces being 32-bit changes nothing on screen; menus stay
   8-bit. Seen with a debugger attached (v1.2, Windows 11): several access violations per movie without the patch,
   none with it.

10. Movie backdrop kept hidden (HGSHELL.DLL, v1.0 and v1.2; on by default under Wine: moviebg)
   For a full-screen movie the shell opens a black pop-up window the size of the screen as it was when the shell started
   (GetSystemMetrics) and plays the movie in a 640x480 child of its main window. Inside gamescope without a Wine virtual
   desktop (how linux/run-heavygear.sh runs the high-resolution Direct3D 9 renderer) gamescope shows one top-level window, the
   newest: the black backdrop, so movies play unseen. The patch changes the backdrop's ShowWindow(SW_SHOWNORMAL) to
   SW_HIDE (v1.0 0x1003114b, v1.2 0x10031ac8: "push 1" -> "push 0"). The window still exists; it was only ever black.

11. Borderless window (HGSHELL.DLL and HG.EXE, v1.2, Wine only; off unless asked for: --fix borderless)
   The shell opens its display in its own windowed GDI mode (5) instead of full-screen DirectDraw (3), with the two
   original bugs that stopped that mode from drawing fixed. The window is a borderless pop-up covering the desktop;
   the 640x480 picture is stretched into the largest centred 4:3 rectangle with black bars, and mouse positions are
   mapped back. No display-mode switch happens, so 'display', 'moviebg' and 'movie32' are not needed and are dropped.
   Details and addresses: docs/research/shell-display.md.

How: new code goes in a small added section ".hgfix" (HGSHELL, and HGSIM v1.2) or in INT3
padding (HGSIM v1.0).
It only uses relative calls and finds its own address at run time (call/pop), because
HGSHELL is usually loaded away from its preferred base (ANET2.DLL takes 0x10000000); the
relocation entry under the one overwritten absolute-address instruction is disabled.

Usage:
  hgfix.py GAME_DIR [--platform auto|wine|windows] [--fix NAME ...] [--skip NAME ...]
                    [--menu-fps 30] [--sim-fps 30]
  hgfix.py GAME_DIR --list
  hgfix.py GAME_DIR --restore
Backups are kept as HGSHELL.DLL.orig / HGSIM.DLL.orig (/ HG.EXE.orig); re-running re-patches
from them.
"""
import argparse, filecmp, os, shutil, stat, struct, sys

MODEFIX_AFTER = 20      # consecutive failed Restore() calls before forcing the display mode

# name: (platforms it is on by default for, description)
FIXES = {
    'limiter': (('wine', 'windows'), 'frame limiter for menus and missions'),
    'display': (('wine',),           'keep 256-colour mode after missions; desktop mode before movies'),
    'palette': ((),                  'experimental: re-send the shell palette once after HGSHELL loads'),
    'dx5draw': (('windows',),        "set PLUGIN\\DX5DRAW.DLL aside: no red menus after a mission on Windows; drops the game's Direct3D renderer"),
    'anet2':  (('wine', 'windows'), "don't unload ANET2.DLL before missions (v1.2 mission-start freeze)"),
    'moviebg': (('wine',),           'keep the black movie backdrop hidden: movies show without a Wine virtual desktop (HD Direct3D 9 renderer)'),
    'nodisc':  ((),                    'play without disc 2 in the drive: cutscenes are read from the VIDEO folder in the game folder'),
    'music':   ((),                    'play the soundtrack from MUSIC\\TRACKnn files instead of the CD (turns on nodisc; needs hgcd.dll)'),
    'partdepth': ((),                  'particle sprites get their real depth (v1.2; on by default for v1.2)'),
    'movie32': (('windows',),        'movie screens ask for 32-bit colour, not 16-bit: no crash around movies on Windows'),
    'glide':  ((),                    'RETIRED, superseded by the tools/glidelog proxy: per-texture colour key (particles)'),
    'borderless': ((),                'menus and movies in one borderless full-screen window, scaled, no display-mode switches (v1.2; on by default for v1.2)'),
}
# A fix that makes others unnecessary: they are dropped when it is chosen.
REPLACES = {'borderless': ('display', 'moviebg', 'movie32')}

# Fixes that only exist for the official 1.2 build, and are on by default once the game is at 1.2.
V12_DEFAULT_FIXES = ('partdepth', 'borderless')

def detect_platform():
    return 'windows' if os.name == 'nt' else 'wine'

def choose_fixes(platform, fix, skip, version=None):
    bad = [n for n in fix + skip if n not in FIXES]
    if bad:
        raise SystemExit(f'unknown fix {", ".join(bad)}; known: {", ".join(FIXES)}')
    on = {n for n, (plats, _) in FIXES.items() if platform in plats}
    if version == '1.2':
        on |= set(V12_DEFAULT_FIXES)
    chosen = (on | set(fix)) - set(skip)
    if platform == 'windows':
        chosen.discard('display')         # Wine only (see the docstring)
    for n, dropped in REPLACES.items():
        if n in chosen:
            chosen -= set(dropped)
    return chosen

# ------------------------------------------------------------------------------- PE helpers
class PEFile:
    def __init__(self, data):
        self.d = data
        self.e = struct.unpack_from('<I', data, 0x3c)[0]
        self.opt = self.e + 24
        self.optsz = struct.unpack_from('<H', data, self.e + 20)[0]
        self.base = struct.unpack_from('<I', data, self.opt + 28)[0]

    @property
    def nsec(self): return struct.unpack_from('<H', self.d, self.e + 6)[0]

    def sec_hdr(self, i): return self.opt + self.optsz + 40 * i

    def sections(self):
        out = []
        for i in range(self.nsec):
            o = self.sec_hdr(i)
            name = self.d[o:o+8].rstrip(b'\0').decode()
            vsize, va, rsize, rptr = struct.unpack_from('<IIII', self.d, o + 8)
            out.append(dict(name=name, vsize=vsize, va=va, rsize=rsize, rptr=rptr, hdr=o))
        return out

    def off(self, va):
        rva = va - self.base
        for s in self.sections():
            if s['va'] <= rva < s['va'] + s['rsize']:
                return s['rptr'] + rva - s['va']
        raise ValueError(f'VA {va:#x} not in file')

    def add_section(self, name, size, chars=0xE0000020):
        """Append a new section (default: code, readable, writable, executable)."""
        salign = struct.unpack_from('<I', self.d, self.opt + 32)[0]
        falign = struct.unpack_from('<I', self.d, self.opt + 36)[0]
        hdr_size = struct.unpack_from('<I', self.d, self.opt + 60)[0]
        secs = self.sections()
        o = self.sec_hdr(self.nsec)
        if o + 40 > hdr_size or any(self.d[o:o+40]):
            raise SystemExit('no room for another section header')
        va = max(s['va'] + max(s['vsize'], s['rsize']) for s in secs)
        va = (va + salign - 1) // salign * salign
        raw = (size + falign - 1) // falign * falign
        rptr = (len(self.d) + falign - 1) // falign * falign
        self.d.extend(b'\0' * (rptr + raw - len(self.d)))
        struct.pack_into('<8sIIIIIIHHI', self.d, o, name.encode(), size, va, raw, rptr, 0, 0, 0, 0, chars)
        struct.pack_into('<H', self.d, self.e + 6, self.nsec + 1)
        struct.pack_into('<I', self.d, self.opt + 56, (va + size + salign - 1) // salign * salign)  # SizeOfImage
        return self.base + va

    def int3_cave(self, need):
        s = self.sections()[0]; assert s['name'] == '.text'
        text = self.d[s['rptr']:s['rptr'] + min(s['vsize'], s['rsize'])]
        run = 0
        for i, b in enumerate(text):
            run = run + 1 if b == 0xcc else 0
            if run >= need + 32:
                return self.base + s['va'] + (i - run + 1 + 16)
        return None

    def disable_reloc(self, va):
        rva, size = struct.unpack_from('<II', self.d, self.opt + 96 + 5 * 8)
        off = self.off(self.base + rva); end = off + size
        target = va - self.base
        while off < end:
            page, bsz = struct.unpack_from('<II', self.d, off)
            if bsz < 8: break
            for k in range((bsz - 8) // 2):
                o = off + 8 + 2 * k
                ent = struct.unpack_from('<H', self.d, o)[0]
                if ent >> 12 == 3 and page + (ent & 0xfff) == target:
                    struct.pack_into('<H', self.d, o, ent & 0x0fff)    # -> ABSOLUTE (ignored)
                    return
            off += bsz
        raise SystemExit(f'relocation entry for {va:#x} not found')

def rel32(frm_next, to):
    return struct.pack('<i', to - frm_next)

# ---------------------------------------------------------------------------- code builders
def build_palette_refresh(at, latch_va, palette_flag):
    c = bytearray()
    c += b'\xe8\x00\x00\x00\x00'                 # call $+5
    c += b'\x5a'                                 # pop edx
    here = at + 5
    d = lambda va: struct.pack('<i', va - here)
    c += b'\x83\xba' + d(latch_va) + b'\x00'      # cmp dword [latch],0
    once = len(c); c += b'\x75\x00'               # jne done
    c += b'\xc7\x82' + d(latch_va) + struct.pack('<I', 1)  # mov dword [latch],1
    c += b'\xc7\x81' + struct.pack('<I', palette_flag) + struct.pack('<I', 1)  # request palette resend
    c[once + 1] = len(c) - (once + 2)
    return bytes(c)

def build_limiter(at, timefn, period_ms, displaced, resume, palette_latch=None, palette_flag=None):
    """Optionally wait for a frame boundary, then run the displaced bytes and jump back."""
    c = bytearray()
    c += b'\x51\x53\x56'                                   # push ecx; push ebx; push esi
    if palette_latch is not None:
        c += build_palette_refresh(at + len(c), palette_latch, palette_flag)
    if period_ms is not None:
        c += b'\xe8' + rel32(at + len(c) + 5, timefn)      # call timeGetTime wrapper
        c += b'\x31\xd2'                                   # xor edx,edx
        c += b'\xbb' + struct.pack('<I', period_ms)        # mov ebx,period
        c += b'\xf7\xf3'                                   # div ebx
        c += b'\x89\xc6'                                   # mov esi,eax
        loop = len(c)
        c += b'\xf3\x90'                                   # pause
        c += b'\xe8' + rel32(at + len(c) + 5, timefn)      # call timeGetTime wrapper
        c += b'\x31\xd2\xf7\xf3'                           # xor edx,edx; div ebx
        c += b'\x39\xf0'                                   # cmp eax,esi
        c += b'\x74' + struct.pack('<b', loop - (len(c) + 2))  # je loop
    c += b'\x5e\x5b\x59'                                   # pop esi; pop ebx; pop ecx
    c += displaced
    c += b'\xe9' + rel32(at + len(c) + 5, resume)          # jmp resume
    return bytes(c)

def build_modefix(at, m, counter_va, threshold):
    c = bytearray()
    c += b'\xe8\x00\x00\x00\x00'                 # call $+5
    c += b'\x5a'                                 # pop edx   (edx = run-time address of here)
    here = at + 5
    d = lambda va: struct.pack('<i', va - here)
    c += b'\x85\xc0'                             # test eax,eax          Restore() ok?
    jz_ok = len(c); c += b'\x74\x00'             # jz ok
    c += b'\xff\x82' + d(counter_va)             # inc dword [counter]
    c += b'\x83\xba' + d(counter_va) + bytes([threshold])   # cmp dword [counter],threshold
    jb_done = len(c); c += b'\x72\x00'           # jb done               (not stuck yet)
    c += b'\x8b\x82' + d(m['ddraw'])             # mov eax,[ddraw]
    c += b'\x52'                                 # push edx
    c += b'\x6a\x08'                             # push 8                bpp
    c += b'\xff\xb2' + d(m['height'])            # push [height]
    c += b'\xff\xb2' + d(m['width'])             # push [width]
    c += b'\x50'                                 # push eax              this
    c += b'\x8b\x08'                             # mov ecx,[eax]
    c += b'\xff\x51\x54'                         # call [ecx+0x54]       IDirectDraw::SetDisplayMode
    c += b'\x5a'                                 # pop edx
    c += b'\x8b\x82' + d(m['primary'])           # mov eax,[primary]
    c += b'\x52'                                 # push edx
    c += b'\x50'                                 # push eax              this
    c += b'\x8b\x08'                             # mov ecx,[eax]
    c += b'\xff\x51\x6c'                         # call [ecx+0x6c]       IDirectDrawSurface::Restore
    c += b'\x5a'                                 # pop edx
    c += b'\x85\xc0'                             # test eax,eax
    jnz_done = len(c); c += b'\x75\x00'          # jnz done              (keep counting if it failed)
    # The mode switch drops the 8-bit palette: ask the shell to re-send it on the next frame,
    # exactly as it does when the window regains focus (app->+0x1dc = 1).
    c += b'\x8b\x8a' + d(m['app'])               # mov ecx,[app]
    c += b'\x85\xc9'                             # test ecx,ecx
    c += b'\x74\x0a'                             # jz ok
    c += b'\xc7\x81' + struct.pack('<I', m['palette_flag']) + struct.pack('<I', 1)  # mov dword [ecx+flag],1
    c[jz_ok + 1] = len(c) - (jz_ok + 2)          # ok:
    c += b'\x83\xa2' + d(counter_va) + b'\x00'   # and dword [counter],0
    c[jb_done + 1] = len(c) - (jb_done + 2)      # done:
    c[jnz_done + 1] = len(c) - (jnz_done + 2)
    c += b'\x89\x82' + d(m['result'])            # mov [result],eax      (displaced instruction)
    c += b'\xe9' + rel32(at + len(c) + 5, m['resume'])
    return bytes(c)

def build_coopfix(at, c):
    """After SetDisplayMode(w, h, 8): store the result (displaced instruction) and, if it
    succeeded, call IDirectDraw::SetDisplayMode(w, h, 8) once more (undoes the mode Wine re-applies
    when the window is activated during the first call) and then SetCooperativeLevel(ddraw, hwnd,
    flags). w and h are DDRAW_Init's own arguments, [ebp+0xc] and [ebp+0x10], in v1.0 and v1.2.
    Only the 8-bit branch is hooked: doing this for the 16-bit mode used by the movies breaks their drawing."""
    b = bytearray()
    b += b'\xe8\x00\x00\x00\x00'                 # call $+5
    b += b'\x5a'                                 # pop edx
    here = at + 5
    d = lambda va: struct.pack('<i', va - here)
    b += b'\x89\x82' + d(c['result'])            # mov [result],eax      (displaced)
    b += b'\x85\xc0'                             # test eax,eax
    b += b'\x75\x2a'                             # jnz done
    b += b'\x52'                                 # push edx              (base)     1
    b += b'\x8b\x82' + d(c['ddraw'])             # mov eax,[ddraw]                  6
    b += b'\x6a\x08'                             # push 8                           2
    b += b'\xff\x75\x10'                         # push [ebp+0x10]       height     3
    b += b'\xff\x75\x0c'                         # push [ebp+0x0c]       width      3
    b += b'\x50'                                 # push eax              this       1
    b += b'\x8b\x08'                             # mov ecx,[eax]                    2
    b += b'\xff\x51\x54'                         # call [ecx+0x54]  SetDisplayMode  3
    b += b'\x5a'                                 # pop edx                          1
    b += b'\x8b\x82' + d(c['ddraw'])             # mov eax,[ddraw]                  6
    b += b'\x6a' + bytes([c['flags']])           # push flags                       2
    b += b'\xff\xb2' + d(c['hwnd'])              # push [hwnd]                      6
    b += b'\x50'                                 # push eax              this       1
    b += b'\x8b\x08'                             # mov ecx,[eax]                    2
    b += b'\xff\x51\x50'                         # call [ecx+0x50]  SetCooperativeLevel 3
    b += b'\xe9' + rel32(at + len(b) + 5, c['resume'])   # done: jmp resume
    return bytes(b)

def build_moviefix(at, m):
    """Before the shell builds a DirectShow graph for a movie, put the desktop display mode back
    (IDirectDraw::RestoreDisplayMode on the shell's DirectDraw object), so the video player is
    set up exactly as it always was before fix 4: it fails to draw if built under 640x480x8."""
    b = bytearray()
    b += b'\xe8\x00\x00\x00\x00'                 # call $+5
    b += b'\x5a'                                 # pop edx
    here = at + 5
    b += b'\x8b\x82' + struct.pack('<i', m['ddraw'] - here)   # mov eax,[ddraw]          6
    b += b'\x85\xc0'                             # test eax,eax                     2
    b += b'\x74\x08'                             # jz skip                          2
    b += b'\x51'                                 # push ecx       (this)            1
    b += b'\x50'                                 # push eax                         1
    b += b'\x8b\x08'                             # mov ecx,[eax]                    2
    b += b'\xff\x51\x4c'                         # call [ecx+0x4c] RestoreDisplayMode 3
    b += b'\x59'                                 # pop ecx                          1
    b += m['orig']                               # skip: displaced prologue
    b += b'\xe9' + rel32(at + len(b) + 5, m['resume'])
    return bytes(b)

# ------------------------------------------------------------------------------- the patches
# Per-version addresses. 'hook' bytes are checked before anything is changed.
PROFILES = {
    '1.0': dict(
        shell=dict(hook=0x1002fc44, orig=bytes.fromhex('558bec51894dfc'), resume=0x1002fc4b,
                   timefn=0x10183b5b),
        modefix=dict(hook=0x10179e1c,                  # "mov [result],eax" after primary->Restore()
                     orig=bytes.fromhex('a370272510'), resume=0x10179e21,
                     ddraw=0x102506f4, primary=0x102506f8,   # IDirectDraw*, primary surface*
                     width=0x10252768, height=0x1025276c,    # mode stored by DDRAW_Init
                     result=0x10252770,                      # "last DirectDraw result"
                     app=0x1023e64c, palette_flag=0x1dc),    # shell app object*, "re-send palette"
        # DDRAW_Init, 8-bit branch only: "mov [result],eax" right after SetDisplayMode(w, h, 8)
        coopfix=dict(hook=0x10177df4, orig=bytes.fromhex('a370272510'), resume=0x10177df9,
                     result=0x10252770, ddraw=0x102506f4, hwnd=0x10250324, flags=0x51),
        # movie player setup (CoCreateInstance(CLSID_FilterGraph)) - entry "push ebp; mov ebp,esp; sub esp,0xc"
        moviefix=dict(hook=0x10022418, orig=bytes.fromhex('558bec83ec0c'), resume=0x1002241e,
                      ddraw=0x102506f4),
        # movie screen (FUN_1003104b): "push 1" of ShowWindow(backdrop, SW_SHOWNORMAL)
        moviebg=dict(va=0x1003114b, orig=bytes.fromhex('6a018b8d10ffffff51ff15'), new=b'\x6a\x00'),
        # sim: the clock is reached through an incremental-link jump stub; replace the stub
        sim=dict(kind='jmp', hook=0x100025ae, orig=bytes.fromhex('e9d0830200'), target=0x1002a983,
                 timefn=0x10002b62),
        # no-disc fix: per shell scan the "cmp eax,5" after GetDriveTypeA and its "%c:\%s\" format string; the sim's cmp and probe path
        nodisc=dict(shell=[(0x100f9e55, 0x10224940), (0x100fa06b, 0x10224948), (0x10128e56, 0x10232e80)],
                    drives=[0x100f9e35, 0x100fa04b, 0x10128e36], drives_iat=0x102e555c, sep=0x10232e5c,
                    sim_cmp=0x10099598, sim_path=0x1014bdc8),
        movie32=0x10177db6,      # DDRAW_Init: "push 16" (bits per pixel) of the SetDisplayMode call the movie screens use
    ),
    '1.2': dict(
        shell=dict(hook=0x100305ce, orig=bytes.fromhex('558bec51894dfc'), resume=0x100305d5,
                   timefn=0x1018728b),
        modefix=dict(hook=0x1017d52c, orig=bytes.fromhex('a3f0b92510'), resume=0x1017d531,
                     ddraw=0x10259974, primary=0x10259978,
                     width=0x1025b9e8, height=0x1025b9ec, result=0x1025b9f0,
                     app=0x1024774c, palette_flag=0x1dc),
        coopfix=dict(hook=0x1017b507, orig=bytes.fromhex('a3f0b92510'), resume=0x1017b50c,
                     result=0x1025b9f0, ddraw=0x10259974, hwnd=0x102595a4, flags=0x51),
        moviefix=dict(hook=0x10022c28, orig=bytes.fromhex('558bec83ec0c'), resume=0x10022c2e,
                      ddraw=0x10259974),
        moviebg=dict(va=0x10031ac8, orig=bytes.fromhex('6a018b8510ffffff50ff15'), new=b'\x6a\x00'),
        # sim: no stubs in this build; redirect the clock's only call site
        sim=dict(kind='call', hook=0x10070d0e, orig=bytes.fromhex('e810f2faff'), target=0x1001ff23,
                 timefn=0x100a13bb),
        nodisc=dict(shell=[(0x100fc477, 0x1022d980), (0x100fc812, 0x1022d9c4), (0x100fc981, 0x1022d9cc), (0x1012b8af, 0x1023bf08)],
                    drives=[0x100fc457, 0x100fc7f2, 0x100fc961, 0x1012b88f], drives_iat=0x101a6080, sep=0x1023bee4,
                    sim_cmp=0x100874e8, sim_path=0x1011eed0),
        movie32=0x1017b4c9,
        # HG.EXE: don't unload ANET2.DLL before a mission (its 1.2 version deadlocks under Wine)
        # sim: plugin start-up block, field +4 hard-coded to 8 ("8-bit palette textures")
        texfix=dict(hook=0x1007098f, orig=bytes.fromhex('c7857cffffff08000000'), resume=0x10070999,
                    hwflag=0x1014b954),
        exe=dict(hook=0x401339, orig=bytes.fromhex('50ffd73bc675f4'), new=bytes.fromhex('31c0903bc675f4')),
        # sim: FUN_10078c29 (draws one particle quad) - the "cmp [ebp+0x10], 0x1ff" before its draw call; locals: depth [ebp-0x1c], screen radius [ebp-8], vertices [ebp-0x10]
        partdepth=dict(entry=0x10078c29, entry_orig=bytes.fromhex('558bec83ec24'), hook=0x10078df8, orig=bytes.fromhex('817d10ff010000'), resume=0x10078dff),
        # 'borderless' (docs/research/shell-display.md). Shell:
        borderless=dict(
            modes=[0x1003022b, 0x10031c86, 0x10031d52],      # "push 3; call display_open": start-up, movie start, after the movie
            gate=0x1003061f, ddraw=0x10259974, dc=0x102599a0,  # draw gate's "cmp [IDirectDraw*],0" operand -> the GDI DC
            # display_open: "mov edx,[ebp-0x14]; cmp edx,[ebp+0x14]" where it picks full-screen or windowed; [ebp-0x14]/[ebp-0x20]
            # = screen size, [ebp+0x14]/[ebp+0x18] = canvas size, [ebp-0x18] = driver; continues at 0x10179930 with both cases set up
            window=0x10179897, window_orig=bytes.fromhex('8b55ec3b5514'), window_resume=0x10179930,
            style=0x10240910, wrect=0x1025c300, wtype=0x10259934,   # GDI driver's window style, window rectangle, window type
            canvas_w=0x1025c78c, canvas_h=0x1025c790, memdc=0x10259dac, result=0x1025b9d0,
            present=0x1017dd3b, present_rect=0x1017dd9e, present_orig=bytes.fromhex('558bec6820'),
            stretch_cmp=0x1017dee1,                            # GDI stretch present: "sub eax,[canvas_h]" of its result test
            bitblt=0x101a6030, stretchblt=0x101a6040, screen_to_client=0x101a6284,   # import slots
            poll=0x100273d7,                                   # mouse poll: "call [ScreenToClient]"
            # mouse poll: "call in_rect(x, y)", the point against the window rectangle kept since start-up (screen
            # coordinates; it matched only because HG.EXE maximised its window). The mapped point is always on the canvas.
            poll_rect=0x100273e8, poll_rect_orig=bytes.fromhex('e8f0000000'),
            mousemsg=0x10034ab6, mousemsg_orig=bytes.fromhex('558bec83ec0c'), mousemsg_resume=0x10034abc,  # WM_*BUTTON*/MOUSEMOVE lParam
            # movie set-up: after the picture (IBasicVideo [ebp-0x20]) and the video window (IVideoWindow [ebp-0x18]) are
            # placed for 640x480 and the window is given its owner: "push 0; mov edx,[ebp-0x18]" (before put_BorderColor).
            # Moved while still top-level, Wine clipped the child as if its offset counted twice.
            movie=0x10022f47, movie_orig=bytes.fromhex('6a008b55e8'), movie_resume=0x10022f4c,
            exe=0x40255b,                                      # HG.EXE: "push 3" (SW_MAXIMIZE) of ShowWindow on its window
        ),
        # 'borderless' in HGSIM's copy of the display library (software missions)
        borderless_sim=dict(
            # the mission display mode's initial value: -1 (a DirectDraw mode) -> 5. Software missions keep it; the hardware
            # paths set their own (0 for DX5DRAW's DirectDraw, 6 for plugins with their own output).
            mode=0x1010f674,
            window=0x1002c057, window_orig=bytes.fromhex('8b55ec3b5514'), window_resume=0x1002c0f0,
            style=0x1011ded0, wrect=0x107edf50, wtype=0x101312fc, canvas_w=0x107ee3cc, canvas_h=0x107ee3d0,
            stretchdibits=0x100eb054, stretchblt=0x100eb030, setdibits=0x100eb058,   # import slots
            # every "call [SetDIBitsToDevice]" of the GDI driver: full and rectangle presents and the screen-shake effect
            blits=[0x1006e8fa, 0x1006e942, 0x1006eab2, 0x1006ebf7, 0x1006ec36, 0x1006ec9c, 0x1006ed22, 0x1006eda8],
            # SimWindowProc's entry: "push ebp; mov ebp,esp; sub esp,0xc"
            winproc=0x10071397, winproc_orig=bytes.fromhex('558bec83ec0c'), winproc_resume=0x1007139d,
            getsystemmetrics=0x100eb1c8, setwindowpos=0x100eb1d4, getwindowrect=0x100eb1cc,
            reclip=0x10148e98,   # set: the next mouse poll confines the cursor to the 640x480 area again and centres it
        ),
    ),
}
OLD_PLUGIN = os.path.join('PLUGIN', 'DX5DRAW.DLL')   # patched by an earlier version; put back
# 3DFXGEAR: "test cl,4; jne done" around grChromakeyMode(1)+grChromakeyValue(key)
GLIDE_PLUGIN = os.path.join('PLUGIN', '3DFXGEAR.DLL')
GLIDE_CHROMA_SIG = ('8a 0d ?? ?? ?? ?? b8 04 00 00 00 84 c8 75 3c 8b 15 ?? ?? ?? ?? 6a 01 0b d0 '
                    '89 15 ?? ?? ?? ?? e8 ?? ?? ?? ?? 55 e8 ?? ?? ?? ?? eb')
GLIDE_CACHE_SIG = '8b 0d ?? ?? ?? ?? 89 48 2c 8b 17 8b 0d ?? ?? ?? ?? 3b 4a 08 74 ?? 57 50 e8'
TIMEFN_BYTES = bytes.fromhex('558bec83ec08ff15')       # push ebp; mov ebp,esp; sub esp,8; call [timeGetTime]

def matches(pe, va, expect):
    try:
        o = pe.off(va)
    except ValueError:
        return False
    return bytes(pe.d[o:o + len(expect)]) == expect

def detect(pe, part):
    for ver, prof in PROFILES.items():
        p = prof[part]
        if matches(pe, p['hook'], p['orig']) and _timefn_ok(pe, p['timefn']):
            return ver, prof
    return None, None

def _timefn_ok(pe, va):
    if matches(pe, va, TIMEFN_BYTES):
        return True
    o = pe.off(va)                                      # v1.0 sim: a jump stub to the helper
    if pe.d[o] == 0xe9:
        return matches(pe, va + 5 + struct.unpack_from('<i', pe.d, o + 1)[0], TIMEFN_BYTES)
    return False

def put(pe, va, b):
    o = pe.off(va); pe.d[o:o + len(b)] = b

def patch_shell(pe, fps, modefix, palette_resend=False):
    """fps None = no menu limiter. Returns (version, period or None, section or None)."""
    ver, prof = detect(pe, 'shell')
    if not ver:
        raise SystemExit('HGSHELL.DLL: not a v1.0 or v1.2 file I know (or already modified). Nothing changed.')
    s, m = prof['shell'], prof['modefix']
    cf, mv = prof['coopfix'], prof['moviefix']
    if modefix and not (matches(pe, m['hook'], m['orig']) and matches(pe, cf['hook'], cf['orig'])
                        and matches(pe, mv['hook'], mv['orig'])):
        raise SystemExit(f'HGSHELL.DLL v{ver}: unexpected bytes at the mode-fix hooks. Nothing changed.')
    if fps is None and not modefix and not palette_resend:
        return ver, None, None
    sec = pe.add_section('.hgfix', 0x200)
    counter = sec                                   # 4-byte counter at the start (writable)
    lim_at = sec + 0x10
    period = None
    end = lim_at
    if fps is not None or palette_resend:
        period = max(1, round(1000 / fps)) if fps is not None else None
        lim = build_limiter(
            lim_at, s['timefn'], period if fps is not None else None, s['orig'], s['resume'],
            sec + 4 if palette_resend else None, m['palette_flag'] if palette_resend else None,
        )
        put(pe, lim_at, lim)
        put(pe, s['hook'], b'\xe9' + rel32(s['hook'] + 5, lim_at) + b'\x90' * (len(s['orig']) - 5))
        end = lim_at + len(lim)
    if modefix:
        mf_at = (end + 15) & ~15
        mfc = build_modefix(mf_at, m, counter, MODEFIX_AFTER)
        put(pe, mf_at, mfc)
        pe.disable_reloc(m['hook'] + 1)
        put(pe, m['hook'], b'\xe9' + rel32(m['hook'] + 5, mf_at))
        cf_at = (mf_at + len(mfc) + 15) & ~15
        cfc = build_coopfix(cf_at, cf)
        mv_at = (cf_at + len(cfc) + 15) & ~15
        mvc = build_moviefix(mv_at, mv)
        assert mv_at + len(mvc) <= sec + 0x200
        put(pe, mv_at, mvc)
        put(pe, mv['hook'], b'\xe9' + rel32(mv['hook'] + 5, mv_at) + b'\x90')
        put(pe, cf_at, cfc)
        pe.disable_reloc(cf['hook'] + 1)
        put(pe, cf['hook'], b'\xe9' + rel32(cf['hook'] + 5, cf_at))
    return ver, period, sec

def patch_moviebg(pe, ver):
    """The 'moviebg' fix (10): the movie backdrop is created hidden. Returns True when patched."""
    m = PROFILES[ver]['moviebg']
    if not matches(pe, m['va'], m['orig']):
        raise SystemExit(f'HGSHELL.DLL v{ver}: unexpected bytes at the movie backdrop. Nothing changed.')
    put(pe, m['va'], m['new'])
    return True

def patch_sim(pe, fps):
    ver, prof = detect(pe, 'sim')
    if not ver:
        raise SystemExit('HGSIM.DLL: not a v1.0 or v1.2 file I know (or already modified). Nothing changed.')
    s = prof['sim']
    period = max(1, round(1000 / fps))
    need = len(build_limiter(0, s['timefn'], period, b'', s['target']))
    at = pe.int3_cave(need) if s['kind'] == 'jmp' else None
    if at is None:
        at = pe.add_section('.hgfix', 0x100)
    put(pe, at, build_limiter(at, s['timefn'], period, b'', s['target']))   # ends: jmp clock
    op = b'\xe9' if s['kind'] == 'jmp' else b'\xe8'
    put(pe, s['hook'], op + rel32(s['hook'] + 5, at))
    return ver, period, at

def build_texfix(at, t):
    """Field +4 of the renderer start-up block = 16 instead of 8 when the device is 3Dfx/PowerVR."""
    b = bytearray()
    b += b'\xe8\x00\x00\x00\x00'                 # call $+5
    b += b'\x58'                                 # pop eax
    here = at + 5
    b += t['orig']                               # mov dword [ebp-0x84],8   (displaced)
    b += b'\x83\xb8' + struct.pack('<i', t['hwflag'] - here) + b'\x00'   # cmp dword [hwflag],0
    b += b'\x74\x0a'                             # je done
    b += b'\xc7\x85\x7c\xff\xff\xff' + struct.pack('<I', 16)       # mov dword [ebp-0x84],16
    b += b'\xe9' + rel32(at + len(b) + 5, t['resume'])                # done: jmp resume
    return bytes(b)

def patch_texfix(pe, ver, sec):
    t = PROFILES[ver].get('texfix')
    if not t or not matches(pe, t['hook'], t['orig']):
        return None
    at = sec + 0x60
    code = build_texfix(at, t)
    put(pe, at, code)
    put(pe, t['hook'], b'\xe9' + rel32(t['hook'] + 5, at) + b'\x90' * (len(t['orig']) - 5))
    return at

def build_partdepth(at, p):
    """Before a particle quad is drawn: store its depth (nearer by 0.2% per pixel of screen radius, at most 50%) in the w and 1/w words of its 4 vertices."""
    c = bytearray()
    c += b'\xe8\x00\x00\x00\x00' + b'\x5a'                    # call $+5; pop edx   (edx = at + 5)
    data = [None]                                              # data offsets are patched in below
    fix = []                                                   # (position of a disp32 to patch, data name)
    def mem(op, name):
        c.extend(op); fix.append((len(c), name)); c.extend(b'\0\0\0\0')
    c += b'\x8b\x45\xe4'                                       # mov eax,[ebp-0x1c]       depth
    c += b'\x3d' + struct.pack('<I', 0x3f800000)               # cmp eax,1.0f             (signed compare: negatives and < 1 skip)
    jl_at = len(c); c += b'\x0f\x8c\0\0\0\0'                    # jl skip
    c += b'\xd9\x45\xf8'                                       # fld dword [ebp-8]        screen radius in pixels
    mem(b'\xd8\x8a', 'k')                                      # fmul dword [edx+k]
    mem(b'\xd8\xaa', 'one')                                    # fsubr dword [edx+one]    st0 = 1.0 - st0
    mem(b'\xd9\x9a', 'tmp')                                    # fstp dword [edx+tmp]
    mem(b'\x8b\x8a', 'tmp')                                    # mov ecx,[edx+tmp]
    c += b'\x81\xf9' + struct.pack('<I', 0x3f000000)           # cmp ecx,0.5f
    c += b'\x7d\x05'                                           # jge ok
    c += b'\xb9' + struct.pack('<I', 0x3f000000)               # mov ecx,0.5f
    mem(b'\x89\x8a', 'tmp')                                    # ok: mov [edx+tmp],ecx    factor
    c += b'\xd9\x45\xe4'                                       # fld dword [ebp-0x1c]
    mem(b'\xd8\x8a', 'tmp')                                    # fmul dword [edx+tmp]
    mem(b'\xd9\x9a', 'tmp')                                    # fstp dword [edx+tmp]     w'
    mem(b'\x8b\x82', 'tmp')                                    # mov eax,[edx+tmp]
    c += b'\x8b\x4d\xf0'                                       # mov ecx,[ebp-0x10]       the vertices
    for off in (0x08, 0x2c, 0x50, 0x74):
        c += b'\x89\x41' + bytes([off])                        # mov [ecx+off],eax        w of vertex 0..3
    c += b'\xd9\xe8'                                           # fld1
    mem(b'\xd8\xb2', 'tmp')                                    # fdiv dword [edx+tmp]     1 / w'
    for off in (0x0c, 0x30, 0x54):
        c += b'\xd9\x51' + bytes([off])                        # fst dword [ecx+off]      1/w of vertex 0..2
    c += b'\xd9\x59\x78'                                       # fstp dword [ecx+0x78]    1/w of vertex 3
    skip = len(c)
    c[jl_at + 2:jl_at + 6] = struct.pack('<i', skip - (jl_at + 6))
    c += p['orig']                                             # cmp dword [ebp+0x10],0x1ff   (displaced)
    c += b'\xe9' + rel32(at + len(c) + 5, p['resume'])
    while len(c) % 4: c += b'\x90'
    names = {}
    for n, v in (('k', struct.pack('<f', 0.002)), ('one', struct.pack('<f', 1.0)), ('tmp', b'\0\0\0\0')):
        names[n] = len(c); c += v
    for pos, n in fix:
        struct.pack_into('<i', c, pos, names[n] - 5)           # relative to edx = at + 5
    return bytes(c)

def patch_partdepth(pe, ver):
    p = PROFILES[ver].get('partdepth')
    if not p:
        return None
    if not (matches(pe, p['entry'], p['entry_orig']) and matches(pe, p['hook'], p['orig'])):
        raise SystemExit('HGSIM.DLL: the particle draw routine is not where partdepth expects it. Nothing changed.')
    at = pe.add_section('.hgdep', 0x100)
    code = build_partdepth(at, p)
    assert len(code) <= 0x100
    put(pe, at, code)
    put(pe, p['hook'], b'\xe9' + rel32(p['hook'] + 5, at) + b'\x90' * (len(p['orig']) - 5))
    return at

EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = range(8)

class _Code:
    """Position-independent x86 for an added section: `getpc` loads the run-time address of the next instruction into a
    register, and `m` addresses any VA of the image relative to it ([reg+disp32]), so no relocation entries are needed."""
    def __init__(self, at):
        self.at, self.c, self.here, self.jumps, self.labels = at, bytearray(), None, [], {}
    def pc(self):
        return self.at + len(self.c)
    def raw(self, b):
        self.c += b
    def getpc(self, reg):
        self.c += b'\xe8\0\0\0\0'                                # call $+5
        self.here = self.pc()                                    # the address it pushes
        self.c += bytes([0x58 + reg])                            # pop reg
    def m(self, op, reg, base, va, imm=b''):
        """op [base+disp32] with /reg; `va` is turned into a displacement from the last getpc."""
        self.c += op + bytes([0x80 | reg << 3 | base]) + struct.pack('<i', va - self.here) + imm
    def jcc(self, op, label):                                    # short jump (op = 0x74 je, 0xeb jmp, ...)
        self.c += bytes([op, 0]); self.jumps.append((len(self.c), label, 1))
    def jcc_near(self, op, label):                               # near conditional jump (op = 0x84 je, ...)
        self.c += bytes([0x0f, op]) + b'\0' * 4; self.jumps.append((len(self.c), label, 4))
    def label(self, name):
        self.labels[name] = len(self.c)
    def call(self, va):
        self.c += b'\xe8' + rel32(self.pc() + 5, va)
    def jmp(self, va):
        self.c += b'\xe9' + rel32(self.pc() + 5, va)
    def done(self):
        for end, name, size in self.jumps:
            self.c[end - size:end] = struct.pack('<b' if size == 1 else '<i', self.labels[name] - end)
        return bytes(self.c)

# 'borderless' data, at the start of its section: desktop size (read once), the picture's rectangle, four black bars
BL_DW, BL_DH, BL_RX, BL_RY, BL_RW, BL_RH, BL_BARS = 0, 4, 8, 12, 16, 20, 24   # bars: 4 x (x, y, w, h)
BL_CODE = 0x60
WS_POPUP_CLIPCHILDREN = 0x82000000

def _bl_window(k, b, D, ent):
    """window: replaces display_open's choice between full screen and a centred window. The window is a borderless
    pop-up the size of the desktop (as it was the first time); the canvas stays the size asked for. HGSHELL and HGSIM
    each have a copy of the display library, so `b` holds the addresses of one of them."""
    ent['window'] = k.pc()
    k.getpc(ECX)
    k.m(b'\x8b', EAX, ECX, D(BL_DW))                    # mov eax,[desk_w]
    k.raw(b'\x85\xc0'); k.jcc(0x75, 'have')             # test eax,eax; jnz have
    k.raw(b'\x8b\x45\xec'); k.m(b'\x89', EAX, ECX, D(BL_DW))   # desk_w = screen width  [ebp-0x14]
    k.raw(b'\x8b\x45\xe0'); k.m(b'\x89', EAX, ECX, D(BL_DH))   # desk_h = screen height [ebp-0x20]
    k.label('have')
    # largest 4:3 (canvas-shaped) rectangle: rw = dh*cw/ch; if that is wider than the desktop, rw = dw, rh = dw*ch/cw
    k.m(b'\x8b', EAX, ECX, D(BL_DH))                    # mov eax,[desk_h]
    k.raw(b'\x0f\xaf\x45\x14\x99\xf7\x7d\x18')          # imul eax,[ebp+0x14]; cdq; idiv dword [ebp+0x18]
    k.m(b'\x3b', EAX, ECX, D(BL_DW))                    # cmp eax,[desk_w]
    k.jcc(0x7e, 'fits')                                 # jle fits
    k.m(b'\x8b', EAX, ECX, D(BL_DW)); k.m(b'\x89', EAX, ECX, D(BL_RW))   # rw = desk_w
    k.raw(b'\x0f\xaf\x45\x18\x99\xf7\x7d\x14')          # imul eax,[ebp+0x18]; cdq; idiv dword [ebp+0x14]
    k.m(b'\x89', EAX, ECX, D(BL_RH))                    # rh = desk_w*ch/cw
    k.jcc(0xeb, 'centre')
    k.label('fits')
    k.m(b'\x89', EAX, ECX, D(BL_RW))                    # rw = desk_h*cw/ch
    k.m(b'\x8b', EAX, ECX, D(BL_DH)); k.m(b'\x89', EAX, ECX, D(BL_RH))   # rh = desk_h
    k.label('centre')
    for pos, size, whole in ((BL_RX, BL_RW, BL_DW), (BL_RY, BL_RH, BL_DH)):
        k.m(b'\x8b', EAX, ECX, D(whole)); k.m(b'\x2b', EAX, ECX, D(size))  # (whole - size) / 2
        k.raw(b'\xd1\xf8'); k.m(b'\x89', EAX, ECX, D(pos))
    bar = lambda i, f: D(BL_BARS + 16 * i + 4 * f)      # field f: 0 x, 1 y, 2 w, 3 h (x and y start at 0)
    k.m(b'\x8b', EAX, ECX, D(BL_RX)); k.m(b'\x89', EAX, ECX, bar(0, 2))          # left:   0, 0, rx, dh
    k.m(b'\x8b', EAX, ECX, D(BL_DH)); k.m(b'\x89', EAX, ECX, bar(0, 3)); k.m(b'\x89', EAX, ECX, bar(1, 3))
    k.m(b'\x8b', EAX, ECX, D(BL_RX)); k.m(b'\x03', EAX, ECX, D(BL_RW))          # right:  rx+rw, 0, dw-(rx+rw), dh
    k.m(b'\x89', EAX, ECX, bar(1, 0)); k.raw(b'\xf7\xd8'); k.m(b'\x03', EAX, ECX, D(BL_DW)); k.m(b'\x89', EAX, ECX, bar(1, 2))
    k.m(b'\x8b', EAX, ECX, D(BL_DW)); k.m(b'\x89', EAX, ECX, bar(2, 2)); k.m(b'\x89', EAX, ECX, bar(3, 2))
    k.m(b'\x8b', EAX, ECX, D(BL_RY)); k.m(b'\x89', EAX, ECX, bar(2, 3))          # top:    0, 0, dw, ry
    k.m(b'\x03', EAX, ECX, D(BL_RH)); k.m(b'\x89', EAX, ECX, bar(3, 1))          # bottom: 0, ry+rh, dw, dh-(ry+rh)
    k.raw(b'\xf7\xd8'); k.m(b'\x03', EAX, ECX, D(BL_DH)); k.m(b'\x89', EAX, ECX, bar(3, 3))
    k.m(b'\xc7', 0, ECX, b['style'], struct.pack('<I', WS_POPUP_CLIPCHILDREN))   # GDI driver's window style
    k.m(b'\x8b', EAX, ECX, D(BL_DW)); k.m(b'\x89', EAX, ECX, b['wrect'] + 8)     # window rectangle 0, 0, dw, dh
    k.m(b'\x8b', EAX, ECX, D(BL_DH)); k.m(b'\x89', EAX, ECX, b['wrect'] + 12)
    k.raw(b'\x8b\x45\xe8\x8b\x40\x04')                  # mov eax,[ebp-0x18]; mov eax,[eax+4]   driver's window type
    k.m(b'\x89', EAX, ECX, b['wtype'])
    k.jmp(b['window_resume'])

def build_borderless(sec, b):
    """The shell's borderless routines in a section at `sec`. Returns (bytes, entry points by name)."""
    D = lambda off: sec + off
    k = _Code(sec + BL_CODE)
    ent = {}
    _bl_window(k, b, D, ent)
    # present: replaces the GDI full and rectangle presents. Black bars, then the canvas stretched into the rectangle.
    # Returns 0 when StretchBlt worked (the original compared BitBlt's TRUE with the screen height: always "failed").
    ent['present'] = k.pc()
    k.raw(b'\x53\x56\x57')                              # push ebx; push esi; push edi
    k.getpc(EBX)
    k.m(b'\x8b', ESI, EBX, b['dc'])                     # mov esi,[window DC]
    k.m(b'\x8d', EDI, EBX, D(BL_BARS))                  # lea edi,[bars]
    k.label('bar')
    k.raw(b'\x6a\x42\x6a\x00\x6a\x00\x6a\x00')          # push BLACKNESS; push 0 (y1); push 0 (x1); push 0 (no source)
    k.raw(b'\xff\x77\x0c\xff\x77\x08\xff\x77\x04\xff\x37\x56')   # push h, w, y, x; push esi
    k.m(b'\xff', 2, EBX, b['bitblt'])                   # call [BitBlt]
    k.raw(b'\x83\xc7\x10')                              # add edi,16
    k.m(b'\x8d', EAX, EBX, D(BL_BARS + 64)); k.raw(b'\x39\xc7')   # lea eax,[bars end]; cmp edi,eax
    k.jcc(0x72, 'bar')                                  # jb bar
    k.raw(b'\x68' + struct.pack('<I', 0xcc0020))        # push SRCCOPY
    k.m(b'\xff', 6, EBX, b['canvas_h']); k.m(b'\xff', 6, EBX, b['canvas_w'])
    k.raw(b'\x6a\x00\x6a\x00')                          # source 0, 0
    k.m(b'\xff', 6, EBX, b['memdc'])
    for f in (BL_RH, BL_RW, BL_RY, BL_RX):
        k.m(b'\xff', 6, EBX, D(f))
    k.raw(b'\x56')                                      # push esi
    k.m(b'\xff', 2, EBX, b['stretchblt'])               # call [StretchBlt]
    k.m(b'\x89', EAX, EBX, b['result'])                 # last result, as the original kept it
    k.raw(b'\x83\xf8\x01\x19\xc0')                      # cmp eax,1; sbb eax,eax   (0 ok, -1 failed)
    k.raw(b'\x5f\x5e\x5b\xc3')
    # map: the POINT at [eax] from window to canvas coordinates, clamped to the canvas. Uses eax, ecx, edx.
    ent['map'] = k.pc()
    k.raw(b'\x56\x89\xc6')                              # push esi; mov esi,eax
    k.getpc(ECX)
    k.m(b'\x83', 7, ECX, D(BL_RW), b'\x00')             # cmp dword [rw],0   (no window yet: leave the point)
    k.jcc(0x74, 'mapped')
    for f, pos, size, canvas in ((0, BL_RX, BL_RW, b['canvas_w']), (4, BL_RY, BL_RH, b['canvas_h'])):
        k.raw(b'\x8b\x46' + bytes([f]))                 # mov eax,[esi+f]
        k.m(b'\x2b', EAX, ECX, D(pos))                  # sub eax,[pos]
        k.m(b'\x0f\xaf', EAX, ECX, canvas)              # imul eax,[canvas]
        k.raw(b'\x99'); k.m(b'\xf7', 7, ECX, D(size))   # cdq; idiv dword [size]
        k.raw(b'\x85\xc0\x7d\x02\x31\xc0')              # test eax,eax; jge +2; xor eax,eax
        k.m(b'\x8b', EDX, ECX, canvas); k.raw(b'\x4a')  # mov edx,[canvas]; dec edx
        k.raw(b'\x39\xd0\x7e\x02\x89\xd0')              # cmp eax,edx; jle +2; mov eax,edx
        k.raw(b'\x89\x46' + bytes([f]))                 # mov [esi+f],eax
    k.label('mapped')
    k.raw(b'\x5e\xc3')                                  # pop esi; ret
    # poll: stands in for ScreenToClient(hwnd, &pt) in the shell's mouse poll, then maps the point
    ent['poll'] = k.pc()
    k.getpc(EAX)
    k.raw(b'\xff\x74\x24\x08\xff\x74\x24\x08')          # push [esp+8] (pt); push [esp+8] (hwnd)
    k.m(b'\xff', 2, EAX, b['screen_to_client'])         # call [ScreenToClient]
    k.raw(b'\x8b\x44\x24\x08')                          # mov eax,[esp+8]
    k.call(ent['map'])
    k.raw(b'\xc2\x08\x00')                              # ret 8
    # mousemsg: entry of the routine every mouse message passes its lParam through; maps lParam first
    ent['mousemsg'] = k.pc()
    k.raw(b'\x8b\x44\x24\x04\x51')                      # mov eax,[esp+4] (lParam); push ecx
    k.raw(b'\x0f\xbf\xd0\xc1\xf8\x10\x50\x52')          # movsx edx,ax; sar eax,16; push eax (y); push edx (x)
    k.raw(b'\x89\xe0'); k.call(ent['map'])              # mov eax,esp; call map
    k.raw(b'\x5a\x58\xc1\xe0\x10\x0f\xb7\xd2\x09\xd0')  # pop edx; pop eax; shl eax,16; movzx edx,dx; or eax,edx
    k.raw(b'\x59\x89\x44\x24\x04')                      # pop ecx; mov [esp+4],eax
    k.raw(b['mousemsg_orig'])                           # displaced: push ebp; mov ebp,esp; sub esp,0xc
    k.jmp(b['mousemsg_resume'])
    # movie: the picture's destination (in the video window) scaled by rectangle / canvas, and the video window moved
    # onto the rectangle. COM calls through the vtables: IBasicVideo Get/SetDestinationPosition (+0x80/+0x7c),
    # IVideoWindow SetWindowPosition (+0x9c).
    ent['movie'] = k.pc()
    k.raw(b'\x53\x56\x57')                              # push ebx; push esi; push edi
    k.getpc(EBX)
    k.m(b'\x83', 7, EBX, D(BL_RW), b'\x00')             # cmp dword [rw],0
    k.jcc_near(0x84, 'nomovie')
    k.raw(b'\x83\xec\x10\x89\xe6')                      # sub esp,16; mov esi,esp   (left, top, width, height)
    k.raw(b'\x8d\x46\x0c\x50\x8d\x46\x08\x50\x8d\x46\x04\x50\x56')   # push &h, &w, &t, &l
    k.raw(b'\x8b\x45\xe0\x50\x8b\x08\xff\x91' + struct.pack('<I', 0x80))  # push basicvideo; call GetDestinationPosition
    for f, size, canvas in ((0, BL_RW, b['canvas_w']), (8, BL_RW, b['canvas_w']), (4, BL_RH, b['canvas_h']), (12, BL_RH, b['canvas_h'])):
        k.raw(b'\x8b\x46' + bytes([f]))                 # mov eax,[esi+f]
        k.m(b'\x0f\xaf', EAX, EBX, D(size))             # imul eax,[size]
        k.raw(b'\x99'); k.m(b'\xf7', 7, EBX, canvas)     # cdq; idiv dword [canvas]
        k.raw(b'\x89\x46' + bytes([f]))                 # mov [esi+f],eax
    k.raw(b'\xff\x76\x0c\xff\x76\x08\xff\x76\x04\xff\x36')   # push h, w, t, l
    k.raw(b'\x8b\x45\xe0\x50\x8b\x08\xff\x51\x7c')       # push basicvideo; call SetDestinationPosition
    for f in (BL_RH, BL_RW, BL_RY, BL_RX):
        k.m(b'\xff', 6, EBX, D(f))
    k.raw(b'\x8b\x45\xe8\x50\x8b\x08\xff\x91' + struct.pack('<I', 0x9c))  # push videowindow; call SetWindowPosition
    k.raw(b'\x83\xc4\x10')                              # add esp,16
    k.call(ent['present'])                              # black bars now: the shell does not present while a movie plays
    k.label('nomovie')
    k.raw(b'\x5f\x5e\x5b')
    k.raw(b['movie_orig'])                              # displaced
    k.jmp(b['movie_resume'])
    return k.done(), ent

def build_borderless_sim(sec, b):
    """HGSIM's borderless routines: the window, and a stand-in for SetDIBitsToDevice that draws through StretchDIBits
    into the rectangle (black bars first when the whole canvas is drawn). Returns (bytes, entry points by name)."""
    D = lambda off: sec + off
    k = _Code(sec + BL_CODE)
    ent = {}
    _bl_window(k, b, D, ent)
    # blit: stdcall like SetDIBitsToDevice(dc, x, y, w, h, xsrc, ysrc, start, lines, bits, bmi, usage) = [ebp+8..0x34].
    # StretchDIBits reads a bottom-up DIB from its lower-left corner like SetDIBitsToDevice (the game passes start 0).
    ent['blit'] = k.pc()
    k.raw(b'\x55\x89\xe5\x53\x56\x57')                  # push ebp; mov ebp,esp; push ebx; push esi; push edi
    k.getpc(EBX)
    k.m(b'\x83', 7, EBX, D(BL_RW), b'\x00')             # cmp dword [rw],0   (no window yet: the original call)
    k.jcc_near(0x84, 'plain')
    k.raw(b'\x8b\x45\x0c\x0b\x45\x10')                  # mov eax,[ebp+0xc]; or eax,[ebp+0x10]   x | y
    k.jcc(0x75, 'nobars')
    k.raw(b'\x8b\x45\x14'); k.m(b'\x3b', EAX, EBX, b['canvas_w']); k.jcc(0x75, 'nobars')   # w == canvas width
    k.raw(b'\x8b\x45\x18'); k.m(b'\x3b', EAX, EBX, b['canvas_h']); k.jcc(0x75, 'nobars')   # h == canvas height
    k.m(b'\x8d', EDI, EBX, D(BL_BARS))                  # lea edi,[bars]
    k.label('bar')
    k.raw(b'\x6a\x42' + b'\x6a\x00' * 5)                # push BLACKNESS; no source (dc, x, y, w, h = 0)
    k.raw(b'\xff\x77\x0c\xff\x77\x08\xff\x77\x04\xff\x37\xff\x75\x08')   # push h, w, y, x; push dc
    k.m(b'\xff', 2, EBX, b['stretchblt'])               # call [StretchBlt]
    k.raw(b'\x83\xc7\x10')                              # add edi,16
    k.m(b'\x8d', EAX, EBX, D(BL_BARS + 64)); k.raw(b'\x39\xc7')
    k.jcc(0x72, 'bar')
    k.label('nobars')
    k.raw(b'\x68' + struct.pack('<I', 0xcc0020))        # push SRCCOPY
    k.raw(b'\xff\x75\x34\xff\x75\x30\xff\x75\x2c')     # push usage, bmi, bits
    k.raw(b'\xff\x75\x18\xff\x75\x14\xff\x75\x20\xff\x75\x1c')   # push h, w, ysrc, xsrc
    # destination: each edge mapped (pos + edge*size/canvas), the size as the difference, so adjacent pieces meet
    for pos_arg, size_arg, rpos, rsize, canvas in ((0x10, 0x18, BL_RY, BL_RH, b['canvas_h']),
                                                   (0x0c, 0x14, BL_RX, BL_RW, b['canvas_w'])):
        k.raw(b'\x8b\x45' + bytes([pos_arg]) + b'\x03\x45' + bytes([size_arg]))   # mov eax,[pos]; add eax,[size]
        k.m(b'\x0f\xaf', EAX, EBX, D(rsize)); k.raw(b'\x99'); k.m(b'\xf7', 7, EBX, canvas)   # far edge
        k.raw(b'\x89\xc6')                              # mov esi,eax
        k.raw(b'\x8b\x45' + bytes([pos_arg]))          # mov eax,[pos]
        k.m(b'\x0f\xaf', EAX, EBX, D(rsize)); k.raw(b'\x99'); k.m(b'\xf7', 7, EBX, canvas)   # near edge
        k.raw(b'\x29\xc6\x56')                          # sub esi,eax; push esi   (size)
        k.m(b'\x03', EAX, EBX, D(rpos)); k.raw(b'\x50')  # add eax,[rect pos]; push eax   (position, kept for x)
    # stack now: ... h', y', w', x' pushed in the order h, y, w, x; StretchDIBits wants x, y, w, h after dc
    k.raw(b'\x58\x5a\x59\x5e')                          # pop eax (x'); pop edx (w'); pop ecx (y'); pop esi (h')
    k.raw(b'\x56\x52\x51\x50\xff\x75\x08')              # push h', w', y', x'; push dc
    k.m(b'\xff', 2, EBX, b['stretchdibits'])            # call [StretchDIBits]
    k.raw(b'\x85\xc0'); k.jcc(0x74, 'out')              # test eax,eax; jz out   (0: failed, as the original)
    k.raw(b'\x8b\x45\x28')                              # mov eax,[ebp+0x28]   lines, what SetDIBitsToDevice reports
    k.jcc(0xeb, 'out')
    k.label('plain')
    for off in range(0x34, 0x04, -4):
        k.raw(b'\xff\x75' + bytes([off]))               # push the twelve arguments again
    k.m(b'\xff', 2, EBX, b['setdibits'])                # call [SetDIBitsToDevice]
    k.label('out')
    k.raw(b'\x5f\x5e\x5b\x5d\xc2\x30\x00')              # pop edi; pop esi; pop ebx; pop ebp; ret 0x30
    # activate: SimWindowProc's entry. On WM_PAINT a window that is not minimised and not the screen's size is resized
    # to it. Under Wine's emulated display modes a full-screen DirectDraw renderer (DX5DRAW) comes back from alt-tab with
    # the window restored from minimised to the desktop's size inside the re-applied 640x480 mode (Wine resized it to the
    # desktop mode before minimising it), so it is scaled far off the screen. Wine's DirectDraw does that restore while it
    # keeps the window's messages to itself (WM_SIZE never reaches the game); the repaint that follows does. Everywhere
    # else the window already has the screen's size and this changes nothing.
    # The repaint also asks for the mouse to be confined again: the sim does that on WM_ACTIVATEAPP, which Wine's
    # Direct3D keeps from it (nGlide, DX5DRAW), so after alt-tab the cursor stays free, leaves the 640x480 area of the
    # full-screen window and mouse movement stops.
    ent['activate'] = k.pc()
    k.raw(b'\x83\x7c\x24\x08\x0f'); k.jcc_near(0x85, 'go')   # cmp dword [esp+8],WM_PAINT; jne go
    k.raw(b'\x53\x56\x57'); k.getpc(EBX)                 # push ebx; push esi; push edi
    k.m(b'\xc7', 0, EBX, b['reclip'], struct.pack('<I', 1))   # mov dword [reclip],1
    k.raw(b'\x83\xec\x10\x54\xff\x74\x24\x24')          # sub esp,16 (RECT); push esp; push [esp+0x24] (hwnd)
    k.m(b'\xff', 2, EBX, b['getwindowrect'])            # call [GetWindowRect]
    k.raw(b'\x83\x3c\x24\x00'); k.jcc(0x7c, 'same')     # cmp dword [esp],0 (left); jl same   (minimised: -32000)
    k.raw(b'\x6a\x00'); k.m(b'\xff', 2, EBX, b['getsystemmetrics'])   # screen width
    k.raw(b'\x89\xc6\x6a\x01'); k.m(b'\xff', 2, EBX, b['getsystemmetrics'])   # mov esi,eax; screen height
    k.raw(b'\x89\xc7')                                  # mov edi,eax
    k.raw(b'\x8b\x44\x24\x08\x2b\x04\x24\x39\xf0')      # mov eax,[esp+8] (right); sub eax,[esp] (left); cmp eax,esi
    k.jcc(0x75, 'resize')
    k.raw(b'\x8b\x44\x24\x0c\x2b\x44\x24\x04\x39\xf8')  # mov eax,[esp+0xc] (bottom); sub eax,[esp+4] (top); cmp eax,edi
    k.jcc(0x74, 'same')
    k.label('resize')
    k.raw(b'\x6a\x14\x57\x56\x6a\x00\x6a\x00\x6a\x00')  # push NOZORDER|NOACTIVATE, height, width, 0, 0, 0
    k.raw(b'\xff\x74\x24\x38')                          # push [esp+0x38]: hwnd (six values, RECT, edi, esi, ebx, return)
    k.m(b'\xff', 2, EBX, b['setwindowpos'])             # call [SetWindowPos]
    k.label('same')
    k.raw(b'\x83\xc4\x10\x5f\x5e\x5b')                  # add esp,16; pop edi; pop esi; pop ebx
    k.label('go')
    k.raw(b['winproc_orig'])                            # displaced prologue
    k.jmp(b['winproc_resume'])
    return k.done(), ent

BL_MODE = (bytes.fromhex('6a03e8'), bytes.fromhex('6a05e8'))         # push 3 -> push 5 (GDI refresh mode)
BL_STRETCH_CMP = bytes.fromhex('2b05') + struct.pack('<I', 0x1025c790), bytes.fromhex('83f8011bc090')   # -> cmp eax,1; sbb eax,eax
BL_EXE = (bytes.fromhex('6a0356ff15'), bytes.fromhex('6a0156ff15'))  # ShowWindow(SW_MAXIMIZE) -> SW_SHOWNORMAL

def patch_borderless(pe, pe_exe, ver):
    """The 'borderless' fix in HGSHELL.DLL and HG.EXE (docs/research/shell-display.md). Everything is checked first."""
    b = PROFILES[ver].get('borderless')
    if not b:
        raise SystemExit(f'borderless: not available for v{ver}. Nothing changed.')
    shell = [(va, BL_MODE[0]) for va in b['modes']] + [
        (b['gate'], struct.pack('<I', b['ddraw'])), (b['window'], b['window_orig']), (b['present'], b['present_orig']),
        (b['present_rect'], b['present_orig']), (b['stretch_cmp'], BL_STRETCH_CMP[0]),
        (b['poll'], b'\xff\x15' + struct.pack('<I', b['screen_to_client'])), (b['poll_rect'], b['poll_rect_orig']),
        (b['mousemsg'], b['mousemsg_orig']), (b['movie'], b['movie_orig'])]
    for va, old in shell:
        if not matches(pe, va, old):
            raise SystemExit(f'HGSHELL.DLL v{ver}: unexpected bytes at {va:#x} for the borderless fix. Nothing changed.')
    m = PROFILES[ver]['moviebg']                   # the movie backdrop is hidden too: shown, it covers the window and takes its mouse input
    if not matches(pe, m['va'], m['orig']):
        raise SystemExit(f'HGSHELL.DLL v{ver}: unexpected bytes at the movie backdrop. Nothing changed.')
    if pe_exe is None or not matches(pe_exe, b['exe'], BL_EXE[0]):
        raise SystemExit(f'HG.EXE: not the v{ver} file the borderless fix expects (or missing). Nothing changed.')
    sec = pe.add_section('.hgbdr', 0x400)
    code, ent = build_borderless(sec, b)
    assert BL_CODE + len(code) <= 0x400
    put(pe, sec + BL_CODE, code)
    for va in b['modes']:
        put(pe, va, BL_MODE[1])
    put(pe, b['gate'], struct.pack('<I', b['dc']))                   # still an address in the image: its relocation stays
    put(pe, b['window'], b'\xe9' + rel32(b['window'] + 5, ent['window']) + b'\x90')
    for va in (b['present'], b['present_rect']):
        put(pe, va, b'\xe9' + rel32(va + 5, ent['present']))
    pe.disable_reloc(b['stretch_cmp'] + 2)
    put(pe, b['stretch_cmp'], BL_STRETCH_CMP[1])
    pe.disable_reloc(b['poll'] + 2)
    put(pe, b['poll'], b'\xe8' + rel32(b['poll'] + 5, ent['poll']) + b'\x90')
    put(pe, b['poll_rect'], b'\x83\xc4\x08\xb0\x01')          # add esp,8 (its two arguments); mov al,1 (inside)
    put(pe, b['mousemsg'], b'\xe9' + rel32(b['mousemsg'] + 5, ent['mousemsg']) + b'\x90')
    put(pe, b['movie'], b'\xe9' + rel32(b['movie'] + 5, ent['movie']))
    put(pe, m['va'], m['new'])
    put(pe_exe, b['exe'], BL_EXE[1])
    return sec

def patch_borderless_sim(pe, ver):
    """The 'borderless' fix in HGSIM.DLL: software missions draw through GDI into the shell's borderless window."""
    b = PROFILES[ver]['borderless_sim']
    call = b'\xff\x15' + struct.pack('<I', b['setdibits'])
    sites = [(b['mode'], struct.pack('<i', -1)), (b['window'], b['window_orig']), (b['winproc'], b['winproc_orig'])] + [(va, call) for va in b['blits']]
    for va, old in sites:
        if not matches(pe, va, old):
            raise SystemExit(f'HGSIM.DLL v{ver}: unexpected bytes at {va:#x} for the borderless fix. Nothing changed.')
    sec = pe.add_section('.hgbdr', 0x400)
    code, ent = build_borderless_sim(sec, b)
    assert BL_CODE + len(code) <= 0x400
    put(pe, sec + BL_CODE, code)
    put(pe, b['mode'], struct.pack('<I', 5))
    put(pe, b['window'], b'\xe9' + rel32(b['window'] + 5, ent['window']) + b'\x90')
    put(pe, b['winproc'], b'\xe9' + rel32(b['winproc'] + 5, ent['activate']) + b'\x90')
    for va in b['blits']:
        pe.disable_reloc(va + 2)
        put(pe, va, b'\xe8' + rel32(va + 5, ent['blit']) + b'\x90')
    return sec

def patch_exe(pe, ver):
    e = PROFILES[ver].get('exe')
    if not e:
        return False
    if not matches(pe, e['hook'], e['orig']):
        raise SystemExit(f'HG.EXE: not the v{ver} file I expect (or already modified). Nothing changed.')
    put(pe, e['hook'], e['new'])
    return True

NODISC_CMP = (bytes.fromhex('83f805'), bytes.fromhex('39c090'))     # cmp eax,5  ->  cmp eax,eax; nop
NODISC_SHELL_FMT = (b'%c:\\%s\\\0', b'.\\%.*s\\\0')
NODISC_SEP = (b':\\\0', b'\\\0\0')            # the last scan's caller: letter + this + name
NODISC_SIM_PATH = (b' :\\video\\B51MOVIE.AVI\0', b' \\..\\video\\B51MOVIE.AVI\0')

# GetLogicalDriveStringsA(length, buffer) replacement for the shell's scans: one drive, ".\\" (the game folder).
# Position independent (no absolute addresses), so it needs no relocation entries.
NODISC_DRIVES = bytes.fromhex(
    '8b442408'              # mov eax,[esp+8]        ; the buffer
    'c700 2e5c0000'         # mov dword [eax],".\\"
    'c74004 00000000'       # mov dword [eax+4],0    ; end of the list
    'b804000000'            # mov eax,4              ; length
    'c20800')               # ret 8

def patch_nodisc(pe_shell, pe_sim, ver):
    """The 'nodisc' fix (see the docstring). Everything is checked first; nothing changes unless it all matches."""
    n = PROFILES[ver]['nodisc']
    shell = [(va, *NODISC_CMP) for va, _ in n['shell']] + [(fmt, *NODISC_SHELL_FMT) for _, fmt in n['shell']]
    shell.append((n['sep'], *NODISC_SEP))
    sim = [(n['sim_cmp'], *NODISC_CMP), (n['sim_path'], *NODISC_SIM_PATH)]
    call = b'\xff\x15' + struct.pack('<I', n['drives_iat'])             # call [GetLogicalDriveStringsA]
    for pe, edits, name in ((pe_shell, shell, 'HGSHELL.DLL'), (pe_sim, sim, 'HGSIM.DLL')):
        for va, old, new in edits:
            if not matches(pe, va, old):
                raise SystemExit(f'{name} v{ver}: unexpected bytes at {va:#x} for the no-disc fix. Nothing changed.')
            spare = pe.off(va) + len(old)
            if any(pe.d[spare:spare + max(0, len(new) - len(old))]):
                raise SystemExit(f'{name} v{ver}: no room after the string at {va:#x}. Nothing changed.')
    for va in n['drives']:
        if not matches(pe_shell, va, call):
            raise SystemExit(f'HGSHELL.DLL v{ver}: unexpected bytes at {va:#x} for the no-disc fix. Nothing changed.')
    for pe, edits in ((pe_shell, shell), (pe_sim, sim)):
        for va, _, new in edits:
            put(pe, va, new)
    cave = pe_shell.add_section('.nodisc', len(NODISC_DRIVES))            # the shell has no padding long enough
    put(pe_shell, cave, NODISC_DRIVES)
    for va in n['drives']:
        pe_shell.disable_reloc(va + 2)                                        # the old call held an absolute address
        put(pe_shell, va, b'\xe8' + rel32(va + 5, cave) + b'\x90')

MOVIE32 = (bytes.fromhex('6a10'), bytes.fromhex('6a20'))            # push 16  ->  push 32 (bits per pixel)

def patch_movie32(pe, ver):
    """The 'movie32' fix (see the docstring)."""
    va = PROFILES[ver]['movie32']
    if not matches(pe, va, MOVIE32[0]):
        raise SystemExit(f'HGSHELL.DLL v{ver}: unexpected bytes at {va:#x} for the movie32 fix. Nothing changed.')
    put(pe, va, MOVIE32[1])

PROXY_NAME = 'hgcd.dll'
# What the proxy exports (tools/cdaudio/exports.def): HGSIM may import nothing else from WINMM.
HGCD_EXPORTS = {
    'mciSendCommandA', 'mciGetErrorStringA', 'auxGetNumDevs', 'auxGetDevCapsA', 'auxGetVolume', 'auxSetVolume',
    'timeKillEvent', 'timeEndPeriod', 'timeGetDevCaps', 'timeBeginPeriod', 'timeSetEvent', 'timeGetTime',
    'joyGetPosEx', 'joyGetDevCapsA', 'joyGetNumDevs', 'mmioSetInfo', 'mmioSeek', 'mmioAdvance', 'mmioOpenA',
    'mmioDescend', 'mmioRead', 'mmioAscend', 'mmioClose', 'mmioGetInfo',
}

def _cstr(pe, va):
    o = pe.off(va)
    return bytes(pe.d[o:pe.d.index(b'\0', o)])

def winmm_import(pe):
    """(file offset of the WINMM.dll name, the names it imports from it, its descriptor offset), or None."""
    rva, _ = struct.unpack_from('<II', pe.d, pe.opt + 96 + 8)
    o = pe.off(pe.base + rva) if rva else None
    while o is not None:
        ilt, stamp, chain, name, iat = struct.unpack_from('<5I', pe.d, o)
        if not name:
            return None
        if _cstr(pe, pe.base + name).lower() == b'winmm.dll':
            names, t = [], pe.off(pe.base + (ilt or iat))
            while True:
                (thunk,) = struct.unpack_from('<I', pe.d, t)
                if not thunk:
                    break
                names.append(None if thunk >> 31 else _cstr(pe, pe.base + (thunk & 0x7fffffff) + 2).decode())
                t += 4
            return pe.off(pe.base + name), names, o
        o += 20

def patch_winmm_import(pe, name):
    """Point a DLL's WINMM import at hgcd.dll (`name` is the DLL, for messages). Checked first; nothing changes
    unless it all matches."""
    found = winmm_import(pe)
    if not found:
        raise SystemExit(f'{name}: no WINMM import found. Nothing changed.')
    name_off, names, desc = found
    other = sorted(n or 'an ordinal' for n in names if n not in HGCD_EXPORTS)
    if other:
        raise SystemExit(f'{name} imports {", ".join(other)} from WINMM, which hgcd.dll does not provide. Nothing changed.')
    if struct.unpack_from('<I', pe.d, desc + 4)[0]:
        raise SystemExit(f'{name}: its WINMM import is pre-bound; not something hgfix knows. Nothing changed.')
    if bytes(pe.d[name_off:name_off + 10]).lower() != b'winmm.dll\0':
        raise SystemExit(f'{name}: unexpected WINMM import name. Nothing changed.')
    pe.d[name_off:name_off + 10] = PROXY_NAME.encode().ljust(10, b'\0')

def proxy_problem(path):
    """None when `path` is a usable hgcd.dll, else why not. Catches a DLL built wrongly: a missing export, or a
    forwarder to a module that does not exist (some linker versions write "_WINMM.name"), which makes HGSIM.DLL
    fail to load and the game fall back to the shell."""
    try:
        with open(path, 'rb') as f:
            pe = PEFile(bytearray(f.read()))
        if struct.unpack_from('<H', pe.d, pe.e + 4)[0] != 0x14c:
            return 'is not a 32-bit DLL'
        rva, size = struct.unpack_from('<II', pe.d, pe.opt + 96)
        if not rva:
            return 'has no exports'
        d = pe.off(pe.base + rva)
        count, = struct.unpack_from('<I', pe.d, d + 24)
        funcs, names, ords = (pe.off(pe.base + v) for v in struct.unpack_from('<III', pe.d, d + 28))
        found = set()
        for i in range(count):
            name = _cstr(pe, pe.base + struct.unpack_from('<I', pe.d, names + 4 * i)[0]).decode()
            target, = struct.unpack_from('<I', pe.d, funcs + 4 * struct.unpack_from('<H', pe.d, ords + 2 * i)[0])
            found.add(name)
            if rva <= target < rva + size:                                   # a forwarder: "MODULE.function"
                forward = _cstr(pe, pe.base + target).decode()
                if forward.split('.')[0].lower() != 'winmm':
                    return f'forwards {name} to "{forward}", which does not exist'
        missing = sorted(HGCD_EXPORTS - found)
        if missing:
            return f'does not export {", ".join(missing)}'
    except (OSError, ValueError, struct.error, IndexError):
        return 'is not a valid DLL'
    return None

def find_proxy(game_dir, given):
    """Where hgcd.dll comes from: --hgcd (used as given), else the first usable one of the copy bundled in the exe,
    next to this script, the repo's tools/cdaudio build, and last the one already in the game folder (so a newer
    build always replaces an older installed one). When none is usable the first one found is returned, so the
    caller can say what is wrong with it."""
    if given:
        if not os.path.isfile(given):
            sys.exit(f'--hgcd: {given} is not a file. Nothing changed.')
        return given
    here = os.path.dirname(os.path.abspath(__file__))
    first = None
    for c in (os.path.join(getattr(sys, '_MEIPASS', here), PROXY_NAME), os.path.join(here, PROXY_NAME),
              os.path.join(here, '..', 'tools', 'cdaudio', PROXY_NAME), os.path.join(game_dir, PROXY_NAME)):
        if os.path.isfile(c):
            if proxy_problem(c) is None:
                return c
            first = first or c
    return first

TRACK_EXTS = ('.wav', '.mp3', '.wma', '.m4a', '.flac', '.ogg')

def copy_music(game_dir, music_from):
    """For the 'music' fix: copy TRACKnn.<ext> files into GAME_DIR/MUSIC (kept if already there). Returns a line to print."""
    def is_track(n):
        stem, ext = os.path.splitext(n.lower())
        return ext in TRACK_EXTS and stem.startswith('track') and stem[5:].isdigit()
    dest = find_file(game_dir, 'MUSIC') or os.path.join(game_dir, 'MUSIC')
    if music_from:
        src = find_file(music_from, 'MUSIC') or music_from
        names = [n for n in os.listdir(src) if is_track(n) and os.path.isfile(os.path.join(src, n))] if os.path.isdir(src) else []
        if not names:
            sys.exit(f'--music-from: no TRACKnn files (wav, mp3, ...) in {src}. Nothing changed.')
        os.makedirs(dest, exist_ok=True)
        copied = 0
        for n in names:
            if not os.path.exists(os.path.join(dest, n)):
                shutil.copy2(os.path.join(src, n), os.path.join(dest, n))
                copied += 1
        return f'MUSIC: {copied} track file(s) copied from {src}'
    if os.path.isdir(dest) and any(is_track(n) for n in os.listdir(dest)):
        return None
    return (f'WARNING: no TRACKnn files in {dest} - until there are, the game looks for the real CD '
            '(rip the audio tracks of disc 2 there, or use --music-from DIR)')

def find_sig(pe, sig):
    import re
    rx = b''.join(b'.' if t == '??' else re.escape(bytes([int(t, 16)])) for t in sig.split())
    s = pe.sections()[0]
    text = bytes(pe.d[s['rptr']:s['rptr'] + s['rsize']])
    return [pe.base + s['va'] + m.start() for m in re.finditer(rx, text, re.S)]

def patch_glide_plugin(pe):
    """Send the colour key for every colour-keyed texture, with its top (alpha) byte cleared.
    Real Voodoo hardware ignores that byte; the Glide wrappers compare all 32 bits, and 1.2's
    particle palettes carry alpha there, so their black never matched the key."""
    hits = find_sig(pe, GLIDE_CHROMA_SIG)
    if len(hits) != 1:
        return False
    h = hits[0]
    push_at = h + 36                                   # push ebp; call grChromakeyValue
    o = pe.off(push_at)
    if pe.d[o] != 0x55 or pe.d[o + 1] != 0xe8:
        return False
    thunk = push_at + 6 + struct.unpack_from('<i', pe.d, o + 2)[0]
    # room for the new code: the unused tail of .text (raw size > virtual size)
    t = pe.sections()[0]
    cave = pe.base + t['va'] + ((t['vsize'] + 15) & ~15)
    if cave + 0x20 > pe.base + t['va'] + t['rsize']:
        return False
    code = bytearray()
    code += b'\x55'                                    # push ebp           (key)
    code += b'\x81\x24\x24\xff\xff\xff\x00'           # and dword [esp],0x00ffffff
    code += b'\xe8' + rel32(cave + len(code) + 5, thunk)      # call grChromakeyValue
    code += b'\xe9' + rel32(cave + len(code) + 5, push_at + 6) # jmp back (to "jmp done")
    put(pe, cave, bytes(code))
    end = cave + len(code)
    put(pe, push_at, b'\xe9' + rel32(push_at + 5, cave) + b'\x90')
    put(pe, h + 14, b'\x15')        # "already on": jne past both calls -> jne to the key call

    # Texture cache (1.2): the colour-key flag is stored only when a texture is first cached. If the
    # sim preloads a texture with flag 0, later transparent draws (flag 1) never get colour-keying.
    # On a cache hit, take the caller's flag and force a rebind when it changed.
    hits = find_sig(pe, GLIDE_CACHE_SIG)
    if len(hits) == 1:
        c = hits[0]                                  # mov ecx,[lastframe]; mov [eax+0x2c],ecx
        frame_var = struct.unpack_from('<I', pe.d, pe.off(c + 2))[0]
        bound_var = struct.unpack_from('<I', pe.d, pe.off(c + 13))[0]
        cave2 = (end + 15) & ~15
        here = cave2 + 5
        d = lambda va: struct.pack('<i', va - here)
        k = bytearray()
        k += b'\xe8\x00\x00\x00\x00\x5a'               # call $+5; pop edx
        k += b'\x8b\x8a' + d(frame_var)              # mov ecx,[frame_var]       (displaced)
        k += b'\x89\x48\x2c'                         # mov [eax+0x2c],ecx        (displaced)
        k += b'\x8b\x4c\x24\x14'                     # mov ecx,[esp+0x14]        flag argument
        k += b'\x3b\x48\x20'                         # cmp ecx,[eax+0x20]
        k += b'\x74\x0d'                             # je done
        k += b'\x89\x48\x20'                         # mov [eax+0x20],ecx
        k += b'\xc7\x82' + d(bound_var) + b'\xff\xff\xff\xff'   # mov dword [bound_var],-1 (rebind)
        k += b'\xe9' + rel32(cave2 + len(k) + 5, c + 9)            # done: jmp back
        if cave2 + len(k) <= pe.base + t['va'] + t['rsize']:
            put(pe, cave2, bytes(k))
            pe.disable_reloc(c + 2)
            put(pe, c, b'\xe9' + rel32(c + 5, cave2) + b'\x90' * 4)
            end = cave2 + len(k)
    struct.pack_into('<I', pe.d, t['hdr'] + 8, end - pe.base - t['va'])   # VirtualSize
    return True

def find_file(game_dir, name):
    """Case-insensitive lookup; name may contain one subdirectory (PLUGIN\\X.DLL)."""
    d = game_dir
    parts = name.replace('\\', '/').split('/')
    for i, part in enumerate(parts):
        try:
            hit = next((f for f in os.listdir(d) if f.lower() == part.lower()), None)
        except OSError:
            return None
        if hit is None:
            return None
        d = os.path.join(d, hit)
    return d

def pe_stamp(data):
    return struct.unpack_from('<I', data, struct.unpack_from('<I', data, 0x3c)[0] + 8)[0]

def load_original(path):
    with open(path, 'rb') as f:
        cur = f.read()
    if os.path.exists(path + '.orig'):
        with open(path + '.orig', 'rb') as f:
            orig = f.read()
        if pe_stamp(orig) != pe_stamp(cur):
            raise SystemExit(f'{os.path.basename(path)}.orig is from a different game version than '
                             f'{os.path.basename(path)} (left over from before a patch?). Move it away and re-run.')
        return bytearray(orig)
    return bytearray(cur)

def save(path, data):
    if not os.path.exists(path + '.orig'):
        shutil.copy2(path, path + '.orig')
    os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    open(path, 'wb').write(data)

def game_version(game_dir):
    """'1.0' (disc) or '1.2' (official patch) from HGSIM.DLL, or None when it is some other
    build (e.g. the intermediate 1.1) or can't be read. Looks through to HGSIM.DLL.orig."""
    path = find_file(game_dir, 'HGSIM.DLL')
    if not path:
        return None
    try:
        return detect(PEFile(load_original(path)), 'sim')[0]
    except (OSError, ValueError, struct.error, SystemExit):
        return None

ASIDE = '.off'

def selected_renderer(game_dir):
    """The plugin file name DLLFILE.INI selects as the renderer ('' when there is none)."""
    path = find_file(game_dir, 'DLLFILE.INI')
    if not path:
        return ''
    try:
        with open(path, 'rb') as f:
            return f.read().decode('ascii', 'replace').strip().strip('"')
    except OSError:
        return ''

def set_d3d_plugin_aside(game_dir, aside):
    """The 'dx5draw' fix. On Windows the shell probes PLUGIN\\DX5DRAW.DLL right after it has set DirectDraw
    up, and that probe makes the 8-bit compatibility layer drop the menu palette: red menus after a mission
    (docs/NOTES.md, "Red shell after a mission"). Renaming the plugin to DX5DRAW.DLL.off avoids the probe; leaving the
    fix out puts it back. Returns a line to print, or None when there was nothing to do."""
    plugin = find_file(game_dir, OLD_PLUGIN)
    parked = find_file(game_dir, OLD_PLUGIN + ASIDE)
    if aside:
        if plugin and selected_renderer(game_dir).lower() == 'dx5draw.dll':
            return ('DX5DRAW.DLL: NOT set aside, DLLFILE.INI selects it as the renderer '
                    '(pick another renderer, then apply again)')
        if plugin and parked:
            return f'DX5DRAW.DLL: NOT set aside, {os.path.basename(parked)} already exists (move it away)'
        if plugin:
            os.rename(plugin, plugin + ASIDE)
            return 'DX5DRAW.DLL: set aside as DX5DRAW.DLL.off (the game\'s Direct3D renderer is not offered)'
        return 'DX5DRAW.DLL: already set aside' if parked else None
    if parked and not plugin:
        os.rename(parked, parked[:-len(ASIDE)])
        return 'DX5DRAW.DLL: put back'
    return None

VIDEO_PROBE = 'B51MOVIE.AVI'    # the file both game checks look for

def copy_videos(game_dir, disc2):
    """For the 'nodisc' fix: copy disc 2's VIDEO folder into GAME_DIR/VIDEO (files already there are kept).
    Returns a line to print."""
    have = find_file(game_dir, os.path.join('VIDEO', VIDEO_PROBE))
    if disc2:
        src = find_file(disc2, 'VIDEO') or disc2
        if not find_file(src, VIDEO_PROBE):
            sys.exit(f'--disc2: no {VIDEO_PROBE} in {src}; point it at disc 2 or its VIDEO folder. Nothing changed.')
        dest = find_file(game_dir, 'VIDEO') or os.path.join(game_dir, 'VIDEO')
        os.makedirs(dest, exist_ok=True)
        copied = 0
        for name in os.listdir(src):
            to = os.path.join(dest, name)
            if os.path.isfile(os.path.join(src, name)) and not os.path.exists(to):
                shutil.copy2(os.path.join(src, name), to)
                copied += 1
        return f'VIDEO: {copied} file(s) copied from {src}'
    if have:
        return None
    return f'WARNING: {os.path.join(game_dir, "VIDEO", VIDEO_PROBE)} is missing - the game will not start until disc 2\'s VIDEO folder is copied there (--disc2 DIR)'

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game_dir')
    ap.add_argument('--platform', choices=('auto', 'wine', 'windows'), default='auto',
                    help='which default set of fixes to apply (auto: windows on Windows, else wine)')
    ap.add_argument('--fix', action='append', default=[], metavar='NAME', help='also apply this fix')
    ap.add_argument('--skip', action='append', default=[], metavar='NAME', help="don't apply this fix")
    ap.add_argument('--list', action='store_true', help='show the fixes and exit')
    ap.add_argument('--menu-fps', type=float, default=30)
    ap.add_argument('--sim-fps', type=float, default=30)
    ap.add_argument('--no-modefix', action='store_true', help=argparse.SUPPRESS)   # old name: --skip display
    ap.add_argument('--disc2', metavar='DIR', help='with the nodisc fix: copy the VIDEO folder from your disc 2 '
                    '(a mounted disc, a folder copy of it, or its VIDEO folder) into GAME_DIR/VIDEO')
    ap.add_argument('--hgcd', metavar='FILE', help='with the music fix: the hgcd.dll to put in the game folder '
                    '(default: the game folder, next to this script, or tools/cdaudio)')
    ap.add_argument('--music-from', metavar='DIR', help='with the music fix: copy the TRACKnn.wav/.mp3 files from this '
                    'folder (or its MUSIC folder) into GAME_DIR/MUSIC')
    ap.add_argument('--restore', action='store_true', help='put the original files back')
    a = ap.parse_args(argv)
    platform = detect_platform() if a.platform == 'auto' else a.platform
    if a.no_modefix:
        a.skip.append('display')
    version = game_version(a.game_dir)      # so the v1.2-only fixes default on for a 1.2 game
    fixes = choose_fixes(platform, a.fix, a.skip, version)
    if 'music' in fixes:
        fixes.add('nodisc')                  # the game's own "disc in the drive" check comes before any music
    if platform == 'windows' and 'display' in a.fix and not a.list:
        print("note: the 'display' fix is for Wine and is not applied on Windows.")
    for n, dropped in REPLACES.items():
        asked = [d for d in dropped if d in a.fix]
        if n in fixes and asked and not a.list:
            print(f"note: '{n}' replaces {', '.join(repr(d) for d in asked)}; not applied.")
    if a.list:
        for n, (plats, desc) in FIXES.items():
            print(f'  [{"x" if n in fixes else " "}] {n:8} {desc}  (default on: {", ".join(plats)})')
        print(f'platform: {platform}')
        return
    paths = {n: find_file(a.game_dir, n) for n in ('HGSHELL.DLL', 'HGSIM.DLL')}
    for n, p in paths.items():
        if not p:
            sys.exit(f'{n} not found in {a.game_dir}')
    exe = find_file(a.game_dir, 'HG.EXE')
    plugin = find_file(a.game_dir, OLD_PLUGIN)
    glide = find_file(a.game_dir, GLIDE_PLUGIN)
    targets = list(paths.items()) + [('HG.EXE', exe), ('DX5DRAW.DLL', plugin), ('3DFXGEAR.DLL', glide)]
    if a.restore:
        for n, p in targets:
            if p and os.path.exists(p + '.orig'):
                os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE)
                shutil.copy2(p + '.orig', p); os.remove(p + '.orig'); print(f'{n}: restored')
        put_back = set_d3d_plugin_aside(a.game_dir, False)
        if put_back:
            print(put_back)
        return

    pe = PEFile(load_original(paths['HGSHELL.DLL']))
    if 'borderless' in fixes:
        v = detect(pe, 'shell')[0]
        if v and 'borderless' not in PROFILES[v]:
            print(f"note: the 'borderless' fix is not available for v{v} yet; not applied.")
            fixes = choose_fixes(platform, [f for f in a.fix if f != 'borderless'], a.skip + ['borderless'], version)
            if 'music' in fixes:
                fixes.add('nodisc')
    borderless = 'borderless' in fixes
    limiter, display = 'limiter' in fixes, 'display' in fixes
    palette = 'palette' in fixes
    ver, period, sec = patch_shell(pe, a.menu_fps if limiter else None, display, palette)
    moviebg = 'moviebg' in fixes and patch_moviebg(pe, ver)
    pe2 = PEFile(load_original(paths['HGSIM.DLL']))
    sim_ver, _ = detect(pe2, 'sim')
    if not sim_ver:
        sys.exit('HGSIM.DLL: not a v1.0 or v1.2 file I know (or already modified). Nothing changed.')
    if ver != sim_ver:
        sys.exit(f'HGSHELL.DLL is v{ver} but HGSIM.DLL is v{sim_ver} - mixed install? Nothing changed.')
    period2 = at = None
    if limiter:
        _, period2, at = patch_sim(pe2, a.sim_fps)
    dep = None
    if 'partdepth' in fixes:
        dep = patch_partdepth(pe2, sim_ver)
        if dep is None:
            print(f'  (partdepth: not available for v{sim_ver})')
    nodisc = 'nodisc' in fixes
    video_note = None
    if nodisc:
        patch_nodisc(pe, pe2, ver)
        video_note = copy_videos(a.game_dir, a.disc2)      # before anything is saved: a bad --disc2 stops here
    movie32 = 'movie32' in fixes
    if movie32:
        patch_movie32(pe, ver)
    music = 'music' in fixes
    music_note = proxy = None
    if music:
        patch_winmm_import(pe2, 'HGSIM.DLL')
        proxy = find_proxy(a.game_dir, a.hgcd)
        if not proxy:
            sys.exit('hgcd.dll not found: build it (tools/cdaudio/build.sh), download it from a release, or pass '
                     '--hgcd FILE. Without it the game would not start. Nothing changed.')
        problem = proxy_problem(proxy)
        if problem:
            sys.exit(f'{proxy} {problem}: rebuild it (tools/cdaudio/build.sh) or use the one from a release. Nothing changed.')
    if music:
        music_note = copy_music(a.game_dir, a.music_from)
    pe3 = PEFile(load_original(exe)) if exe else None
    exe_fixed = pe3 is not None and 'anet2' in fixes and patch_exe(pe3, ver)
    if borderless:
        patch_borderless(pe, pe3, ver)
        patch_borderless_sim(pe2, ver)
    pe5 = PEFile(load_original(glide)) if glide and 'glide' in fixes else None
    glide_fixed = pe5 is not None and patch_glide_plugin(pe5)

    def write(path, pe_, changed):
        """Save a patched file, or put the original back when this run leaves it unpatched."""
        if not path:
            return
        if changed:
            save(path, pe_.d)
        elif os.path.exists(path + '.orig'):
            os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
            shutil.copy2(path + '.orig', path)
            try:
                os.remove(path + '.orig')
            except OSError:
                pass
    write(paths['HGSHELL.DLL'], pe, sec is not None or nodisc or movie32 or moviebg or borderless)
    if proxy:
        target = os.path.join(a.game_dir, PROXY_NAME)
        if not (os.path.exists(target) and (os.path.samefile(proxy, target) or filecmp.cmp(proxy, target, shallow=False))):
            shutil.copy2(proxy, target)                      # absent, or an older build
    write(paths['HGSIM.DLL'], pe2, limiter or dep is not None or nodisc or music or borderless)
    write(exe, pe3, exe_fixed or borderless)
    write(glide, pe5, glide_fixed)
    plugin_reverted = bool(plugin) and os.path.exists(plugin + '.orig')
    write(plugin, None, False)                       # patched by an old version of this tool
    d3d_note = set_d3d_plugin_aside(a.game_dir, 'dx5draw' in fixes)

    print(f'Heavy Gear v{ver}, fixes for {platform}: {", ".join(n for n in FIXES if n in fixes) or "none"}')
    if limiter:
        print(f'  menus limited to {1000/period:.1f} fps, missions to {1000/period2:.1f} fps')
    if display:
        print('  256-colour mode kept after missions; desktop mode restored before movies')
    if palette:
        print('  shell palette re-sent once after HGSHELL loads (experimental)')
    if nodisc:
        print('  no disc needed: cutscenes are read from the VIDEO folder in the game folder')
    if movie32:
        print('  HGSHELL.DLL: movie screens ask for 32-bit colour')
    if moviebg:
        print('  HGSHELL.DLL: movie backdrop kept hidden')
    if dep is not None:
        print('  HGSIM.DLL: particle sprites carry their depth')
    if borderless:
        print('  HGSHELL.DLL, HGSIM.DLL, HG.EXE: menus, movies and software missions in a borderless full-screen window, scaled (experimental)')
    if exe_fixed:
        print('  HG.EXE: ANET2.DLL kept loaded before missions')
    elif 'anet2' in fixes and ver == '1.0':
        print('  (anet2: not needed on v1.0)')
    if glide_fixed:
        print('  3DFXGEAR.DLL: colour key sent per texture (3Dfx particles)')
    elif 'glide' in fixes and glide:
        print('  3DFXGEAR.DLL: not a version this fix knows; left unchanged')
    if plugin_reverted:
        print('  DX5DRAW.DLL: original restored (no longer patched)')
    if d3d_note:
        print('  ' + d3d_note)
    if video_note:
        print('  ' + video_note)
    if music:
        print('  HGSIM.DLL: sound goes through hgcd.dll (the soundtrack plays from MUSIC\\TRACKnn files)')
    if music_note:
        print('  ' + music_note)

if __name__ == '__main__':
    main()
