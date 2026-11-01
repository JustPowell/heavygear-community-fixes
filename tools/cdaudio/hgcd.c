/* hgcd - disc-free music for Heavy Gear.
   HGSIM.DLL plays the soundtrack through the MCI "cdaudio" device (mciSendCommandA) and sets its volume through the
   aux API. This DLL takes the place of WINMM.dll in HGSIM.DLL's import table (hgfix.py --fix music renames the import
   to "hgcd.dll"). When MUSIC\TRACKnn.<wav|mp3|wma|m4a|flac|ogg> files sit beside it, it presents them to the game as a
   one-CD-audio-device machine: nn is the track number on the original disc. Each track plays through the real MCI
   (device "mpegvideo", which also decodes wav). Without any such file every call is passed to the real WINMM, so a
   real disc still works.
   Needs the "nodisc" fix as well: the game's own "is a disc in the drive" check comes first.
   The game works in whole tracks: it asks for each track's start (MCI_STATUS position, MCI_TRACK) and plays
   from one start to the next, so a position here is "track number + elapsed time" and a play range is a track range.
   Everything else in WINMM is forwarded by the export definitions.
   If a file called hgcd.log exists next to this DLL, every emulated call is written to it.
   Freestanding: only kernel32 imports (the real WINMM is loaded at run time). */
typedef unsigned int U;
typedef unsigned short W;
typedef unsigned char B;
typedef void *HANDLE;
typedef void *HMOD;
__declspec(dllimport) HMOD __stdcall LoadLibraryA(const char *);
__declspec(dllimport) void *__stdcall GetProcAddress(HMOD, const char *);
__declspec(dllimport) U __stdcall GetModuleFileNameA(HMOD, char *, U);
__declspec(dllimport) U __stdcall GetFileAttributesA(const char *);
__declspec(dllimport) U __stdcall GetEnvironmentVariableA(const char *, char *, U);
__declspec(dllimport) HANDLE __stdcall CreateFileA(const char *, U, U, void *, U, U, HANDLE);
__declspec(dllimport) int __stdcall WriteFile(HANDLE, const void *, U, U *, void *);
__declspec(dllimport) int __stdcall CloseHandle(HANDLE);
__declspec(dllimport) U __stdcall GetTickCount(void);
__declspec(dllimport) U __stdcall GetCurrentDirectoryA(U, char *);
__declspec(dllimport) int __stdcall SetCurrentDirectoryA(const char *);

/* MCI constants (mmsystem.h / digitalv.h) */
enum {
    MCI_OPEN = 0x803, MCI_CLOSE = 0x804, MCI_PLAY = 0x806, MCI_SEEK = 0x807, MCI_STOP = 0x808, MCI_PAUSE = 0x809,
    MCI_SET = 0x80d, MCI_SYSINFO = 0x810, MCI_STATUS = 0x814, MCI_RESUME = 0x855, MCI_SETAUDIO = 0x873,
    MCI_FROM = 4, MCI_TO = 8, MCI_STATUS_ITEM = 0x100, MCI_TRACK = 0x10, MCI_OPEN_ELEMENT = 0x200, MCI_OPEN_TYPE = 0x2000,
    MCI_SYSINFO_QUANTITY = 0x100, MCI_SYSINFO_NAME = 0x400, MCI_DEVTYPE_CD_AUDIO = 0x204,
    MCI_STATUS_LENGTH = 1, MCI_STATUS_POSITION = 2, MCI_STATUS_NUMBER_OF_TRACKS = 3, MCI_STATUS_MODE = 4,
    MCI_STATUS_READY = 7, MCI_STATUS_MEDIA_PRESENT = 0xe,
    MCI_MODE_STOP = 0x20d, MCI_MODE_PLAY = 0x20e, MCI_MODE_PAUSE = 0x211,
    MCI_SETAUDIO_ITEM_AND_VALUE = 0x800000 | 0x1000000, MCI_SETAUDIO_VOLUME = 0x4002,
    MCIERR_UNSUPPORTED_FUNCTION = 0x115, MCIERR_DEVICE_NOT_INSTALLED = 0x113,
    FAKE_DEVICE = 0x7c01, MAX_TRACK = 99
};
typedef U (__stdcall *fn_mci)(U, U, U, U *);
typedef U (__stdcall *fn_mcierr)(U, char *, U);
typedef U (__stdcall *fn_auxn)(void);
typedef U (__stdcall *fn_auxcaps)(U, void *, U);
typedef U (__stdcall *fn_auxget)(U, U *);
typedef U (__stdcall *fn_auxset)(U, U);

/* ---------------------------------------------------------------------------------------------- strings, log */
static U slen(const char *s) { U n = 0; while (s[n]) n++; return n; }
static char lower(char c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static int seqi(const char *a, const char *b) { while (*a && lower(*a) == lower(*b)) { a++; b++; } return !*a && !*b; }
static void scopy(char *d, const char *s, U max) { U i = 0; if (!max) return; while (s[i] && i + 1 < max) { d[i] = s[i]; i++; } d[i] = 0; }
static void sadd(char *d, const char *s, U max) { U n = slen(d); scopy(d + n, s, max - n); }

static HANDLE logf = (HANDLE)-1;
static char lb[256]; static int lp;
static void put_s(const char *s) { while (*s && lp < 230) lb[lp++] = *s++; }
static void put_x(U v) { static const char h[] = "0123456789abcdef"; char t[8]; int n = 0; put_s("0x");
    if (!v) { put_s("0"); return; } while (v) { t[n++] = h[v & 15]; v >>= 4; } while (n && lp < 250) lb[lp++] = t[--n]; }
static void log_end(void) { U w; lb[lp++] = '\r'; lb[lp++] = '\n'; if (logf != (HANDLE)-1) WriteFile(logf, lb, lp, &w, 0); lp = 0; }
#define LOG_BEGIN() do { lp = 0; } while (0)

/* ---------------------------------------------------------------------------------------------- state */
static HMOD self, winmm;
static fn_mci real_mci; static fn_mcierr real_err; static fn_auxn real_auxn; static fn_auxcaps real_auxcaps;
static fn_auxget real_auxget; static fn_auxset real_auxset;
static int inited, active, guard_on;
static char dir[260];                      /* folder of this DLL, with a trailing backslash */
static char file[MAX_TRACK + 1][300];      /* "" = no file for that track */
static int last_track;                     /* highest track that has a file */
static enum { S_STOP, S_PLAY, S_PAUSE } state;
static int cur_track, end_track;           /* playing track; first track NOT to play */
static U el;                               /* real MCI device of the file being played, 0 = none */
static U started;                          /* GetTickCount() when it began */
static U aux_vol = 0xffffffff;
static int time_format;

static int exists(const char *p) { return GetFileAttributesA(p) != 0xffffffff; }

static void find_tracks(void) {
    static const char *const ext[] = { "wav", "mp3", "wma", "m4a", "flac", "ogg" };
    char env[260], base[260];
    if (GetEnvironmentVariableA("HGCD_MUSIC", env, sizeof env) && env[0]) {      /* tests, or music kept elsewhere */
        scopy(base, env, sizeof base);
        U n = slen(base); if (base[n - 1] != '\\' && n + 1 < sizeof base) { base[n] = '\\'; base[n + 1] = 0; }
    } else { scopy(base, dir, sizeof base); sadd(base, "MUSIC\\", sizeof base); }
    for (int t = 1; t <= MAX_TRACK; t++) {
        char num[4] = { (char)('0' + t / 10), (char)('0' + t % 10), 0 }, one[3] = { (char)('0' + t), 0, 0 };
        file[t][0] = 0;
        for (int pass = 0; pass < 2 && !file[t][0]; pass++) {
            if (pass == 1 && t >= 10) break;
            for (int e = 0; e < 6 && !file[t][0]; e++) {
                char p[300];
                scopy(p, base, sizeof p); sadd(p, "TRACK", sizeof p); sadd(p, pass ? one : num, sizeof p);
                sadd(p, ".", sizeof p); sadd(p, ext[e], sizeof p);
                if (exists(p)) scopy(file[t], p, sizeof file[t]);
            }
        }
        if (file[t][0]) last_track = t;
    }
}

static void init(void) {
    char me[260]; U n, i;
    if (inited) return;
    inited = 1;
    n = GetModuleFileNameA(self, me, sizeof me);
    for (i = n; i && me[i - 1] != '\\'; i--) { }
    me[i] = 0; scopy(dir, me, sizeof dir);
    { char lg[270]; scopy(lg, dir, sizeof lg); sadd(lg, "hgcd.log", sizeof lg);
      logf = CreateFileA(lg, 0x40000000, 3, 0, 3 /* OPEN_EXISTING */, 0x80, 0);
      if (logf != (HANDLE)-1) { U w; WriteFile(logf, "", 0, &w, 0); } }
    { char vp[300]; scopy(vp, dir, sizeof vp); sadd(vp, "VIDEO\\B51MOVIE.AVI", sizeof vp); guard_on = exists(vp); }
    winmm = LoadLibraryA("winmm.dll");
    if (winmm) {
        real_mci = (fn_mci)GetProcAddress(winmm, "mciSendCommandA");
        real_err = (fn_mcierr)GetProcAddress(winmm, "mciGetErrorStringA");
        real_auxn = (fn_auxn)GetProcAddress(winmm, "auxGetNumDevs");
        real_auxcaps = (fn_auxcaps)GetProcAddress(winmm, "auxGetDevCapsA");
        real_auxget = (fn_auxget)GetProcAddress(winmm, "auxGetVolume");
        real_auxset = (fn_auxset)GetProcAddress(winmm, "auxSetVolume");
    }
    find_tracks();
    active = real_mci && last_track > 0;
    LOG_BEGIN(); put_s("init: "); put_s(active ? "emulating a CD from MUSIC files, last track " : "no music files: passing everything to WINMM, ");
    put_x(last_track); put_s(guard_on ? ", working folder is kept at the game folder" : ""); log_end();
}

/* ---------------------------------------------------------------------------------------------- playing a file */
static void apply_volume(void) {
    U l = aux_vol & 0xffff, r = aux_vol >> 16, v = (l > r ? l : r) * 1000 / 0xffff;
    U p[6] = { 0, MCI_SETAUDIO_VOLUME, v, 0, 0, 0 };
    if (el) {
        U r = real_mci(el, MCI_SETAUDIO, MCI_SETAUDIO_ITEM_AND_VALUE, p);
        LOG_BEGIN(); put_s("  volume "); put_x(v); put_s(" of 1000 -> "); put_x(r); log_end();
    }
}
static void el_close(void) {
    U p[3] = { 0, 0, 0 };
    if (el) { real_mci(el, MCI_CLOSE, 0, p); el = 0; }
}
static U el_status(U item, U *out) {
    U p[4] = { 0, 0, item, 0 }, r = real_mci(el, MCI_STATUS, MCI_STATUS_ITEM, p);
    *out = r ? 0 : p[1]; return r;
}
static U el_start(int t) {
    U p[7] = { 0, 0, (U)"mpegvideo", (U)file[t], 0, 0, 0 }, r, pp[3] = { 0, 0, 0 };
    el_close();
    r = real_mci(0, MCI_OPEN, MCI_OPEN_TYPE | MCI_OPEN_ELEMENT, p);
    if (r) { p[2] = 0; p[1] = 0; r = real_mci(0, MCI_OPEN, MCI_OPEN_ELEMENT, p); }      /* let the extension decide */
    if (r) { LOG_BEGIN(); put_s("  open failed "); put_x(r); log_end(); return r; }
    el = p[1];
    apply_volume();
    r = real_mci(el, MCI_PLAY, 0, pp);
    if (r) { LOG_BEGIN(); put_s("  play failed "); put_x(r); log_end(); el_close(); return r; }
    started = GetTickCount(); cur_track = t; state = S_PLAY;
    return 0;
}
/* the play range was reached or the file ended: start the next track of the range, or stop */
static void refresh(void) {
    U mode;
    if (state != S_PLAY || !el) return;
    if (GetTickCount() - started < 300) return;                     /* the device may not report "playing" at once */
    if (el_status(MCI_STATUS_MODE, &mode) == 0 && mode != MCI_MODE_STOP) return;
    el_close();
    for (int t = cur_track + 1; t < end_track && t <= last_track; t++)
        if (file[t][0] && el_start(t) == 0) return;
    state = S_STOP;
}
static U position_tmsf(void) {
    U ms = 0, m, s, f;
    if (el && el_status(MCI_STATUS_POSITION, &ms)) ms = 0;
    m = ms / 60000; s = ms / 1000 % 60; f = ms % 1000 * 75 / 1000;
    return (U)(cur_track ? cur_track : 1) | m << 8 | s << 16 | f << 24;
}

/* ---------------------------------------------------------------------------------------------- the emulated device */
static U emulate(U msg, U flags, U *p) {
    U r = 0;
    refresh();
    switch (msg) {
    case MCI_SET: time_format = (flags & 0x400) ? (int)p[2] : time_format; break;
    case MCI_CLOSE: case MCI_STOP: case MCI_SEEK: el_close(); state = S_STOP; break;
    case MCI_PAUSE:
        if (el && state == S_PLAY) { U q[3] = { 0, 0, 0 }; real_mci(el, MCI_PAUSE, 0, q); state = S_PAUSE; }
        break;
    case MCI_RESUME:
        if (el && state == S_PAUSE) { U q[3] = { 0, 0, 0 }; real_mci(el, MCI_RESUME, 0, q); state = S_PLAY; }
        break;
    case MCI_PLAY: {
        int from = (flags & MCI_FROM) ? (int)(p[1] & 0xff) : (cur_track ? cur_track : 1);
        int to = last_track + 1;
        if (flags & MCI_TO) { to = (int)(p[2] & 0xff); if (p[2] >> 8) to++; }       /* a start of track n ends the range before n */
        if (from < 1) from = 1;
        end_track = to;
        for (int t = from; t < to && t <= last_track; t++)
            if (file[t][0] && el_start(t) == 0) return 0;
        el_close(); state = S_STOP;
        break; }
    case MCI_STATUS: {
        U item = p[2];
        if (!(flags & MCI_STATUS_ITEM)) return MCIERR_UNSUPPORTED_FUNCTION;
        switch (item) {
        case MCI_STATUS_NUMBER_OF_TRACKS: p[1] = (U)last_track; break;
        case MCI_STATUS_MODE: p[1] = state == S_PLAY ? MCI_MODE_PLAY : state == S_PAUSE ? MCI_MODE_PAUSE : MCI_MODE_STOP; break;
        case MCI_STATUS_POSITION: p[1] = (flags & MCI_TRACK) ? p[3] : position_tmsf(); break;       /* a track's start is just its number */
        case MCI_STATUS_READY: case MCI_STATUS_MEDIA_PRESENT: p[1] = 1; break;
        case MCI_STATUS_LENGTH: p[1] = 0; break;
        default: p[1] = 0; break;
        }
        break; }
    default: r = MCIERR_UNSUPPORTED_FUNCTION; break;
    }
    return r;
}

/* ---------------------------------------------------------------------------------------------- working folder
   With the no-disc fix the game finds its movies by a path relative to its working folder (video\...). Something
   moves that folder during play (a mission), and from then on those movies are not found. timeGetTime is called
   every frame by the shell and the sim, so it is used to notice and put the folder back (at most every 200 ms). */
static U guard_at;
static int same_folder(const char *a, U na, const char *b, U nb) {
    U i;
    if (na != nb) return 0;
    for (i = 0; i < na; i++) if (lower(a[i]) != lower(b[i])) return 0;
    return 1;
}
static void cwd_guard(void) {
    char cur[300]; U n, m, now = GetTickCount();
    if (!guard_on || now - guard_at < 200) return;
    guard_at = now;
    n = GetCurrentDirectoryA(sizeof cur, cur);
    if (!n || n >= sizeof cur) return;
    m = slen(dir);
    if (m > 3 && dir[m - 1] == '\\') m--;                          /* "C:\" keeps its backslash, others lose it */
    if (same_folder(cur, n, dir, m)) return;
    LOG_BEGIN(); put_s("working folder was "); put_s(cur); put_s(", put back to "); put_s(dir); log_end();
    SetCurrentDirectoryA(dir);
}
/* ---------------------------------------------------------------------------------------------- tracing
   Only while hgcd.log AND hgcd.trace both exist beside this DLL (a debugging aid that changes system code in the
   process, so it is never on by accident): to see where the game looks for a movie, three system functions are hooked in place
   (the usual 5-byte "mov edi,edi; push ebp; mov ebp,esp" entry is replaced by a jump, and a small trampoline runs
   those bytes and continues), because the DLLs they live in never unload, unlike the shell:
     msvcrt _access            the shell's "does this folder exist" check in its movie-folder scans
     CoCreateInstance          the DirectShow graph the shell creates to play a movie
     kernelbase CreateFileW    any attempt to open a file whose name contains ".avi", with the result */
__declspec(dllimport) HMOD __stdcall GetModuleHandleA(const char *);
__declspec(dllimport) int __stdcall VirtualProtect(void *, U, U, U *);
__declspec(dllimport) void *__stdcall VirtualAlloc(void *, U, U, U);
__declspec(dllimport) U __stdcall GetLastError(void);
__declspec(dllimport) void __stdcall SetLastError(U);
typedef int (__cdecl *fn_access)(const char *, int);
typedef U (__stdcall *fn_cocreate)(const U *, void *, U, const U *, void **);
typedef HANDLE (__stdcall *fn_createfilew)(const W *, U, U, void *, U, U, HANDLE);
static fn_access real_access;
static fn_cocreate real_cocreate;
static fn_createfilew real_createfilew;
static void put_cwd(void) { char cur[300]; if (GetCurrentDirectoryA(sizeof cur, cur)) { put_s(" cwd="); put_s(cur); } }
static int __cdecl trace_access(const char *path, int mode) {
    int r = real_access(path, mode);
    LOG_BEGIN(); put_s("_access("); put_s(path ? path : "(null)"); put_s(") -> "); put_x((U)r); put_cwd(); log_end();
    return r;
}
static U __stdcall trace_cocreate(const U *clsid, void *outer, U ctx, const U *iid, void **out) {
    U r = real_cocreate(clsid, outer, ctx, iid, out);
    if (clsid && clsid[0] == 0xe436ebb3) { LOG_BEGIN(); put_s("movie player (DirectShow graph) created -> "); put_x(r); log_end(); }
    return r;
}
static HANDLE __stdcall trace_createfilew(const W *name, U access, U share, void *sa, U disp, U flags, HANDLE tmpl) {
    HANDLE h = real_createfilew(name, access, share, sa, disp, flags, tmpl);
    U err = GetLastError(), n = 0, avi = 0;
    if (name) { while (name[n]) n++; for (U i = 0; i + 3 < n; i++) if (name[i] == '.' && (name[i + 1] | 32) == 'a' && (name[i + 2] | 32) == 'v' && (name[i + 3] | 32) == 'i') avi = 1; }
    if (avi) {
        char narrow[200]; U i;
        for (i = 0; i < n && i < sizeof narrow - 1; i++) narrow[i] = name[i] < 128 ? (char)name[i] : '?';
        narrow[i] = 0;
        LOG_BEGIN(); put_s("open "); put_s(narrow); put_s(h == (HANDLE)-1 ? " -> FAILED, error " : " -> ok "); if (h == (HANDLE)-1) put_x(err); put_cwd(); log_end();
        SetLastError(err);
    }
    return h;
}
static void *inline_hook(B *target, void *hook) {                 /* the trampoline to call the original, or 0 */
    static const B entry[5] = { 0x8b, 0xff, 0x55, 0x8b, 0xec };
    B *tramp; U prot, i;
    if (!target) return 0;
    for (i = 0; i < 5; i++) if (target[i] != entry[i]) return 0;
    tramp = (B *)VirtualAlloc(0, 16, 0x3000 /* commit | reserve */, 0x40 /* execute read write */);
    if (!tramp) return 0;
    for (i = 0; i < 5; i++) tramp[i] = entry[i];
    tramp[5] = 0xe9; *(U *)(tramp + 6) = (U)(target + 5) - (U)(tramp + 10);
    if (!VirtualProtect(target, 5, 0x40, &prot)) return 0;
    target[0] = 0xe9; *(U *)(target + 1) = (U)hook - (U)(target + 5);
    VirtualProtect(target, 5, prot, &prot);
    return tramp;
}
static void trace_start(void) {
    static int done;
    HMOD m;
    if (done || logf == (HANDLE)-1) return;
    done = 1;
    { char t[300]; scopy(t, dir, sizeof t); sadd(t, "hgcd.trace", sizeof t); if (!exists(t)) return; }   /* its own opt-in file */
    { char me[300]; if (GetModuleFileNameA(self, me, sizeof me)) LoadLibraryA(me); }   /* stay loaded: HG.EXE unloads the shell (and with
                                                                                          it this DLL) for every mission, and the hooks point here */
    m = GetModuleHandleA("msvcrt.dll");
    real_access = (fn_access)inline_hook(m ? (B *)GetProcAddress(m, "_access") : 0, (void *)trace_access);
    m = GetModuleHandleA("combase.dll"); if (!m) m = GetModuleHandleA("ole32.dll");
    real_cocreate = (fn_cocreate)inline_hook(m ? (B *)GetProcAddress(m, "CoCreateInstance") : 0, (void *)trace_cocreate);
    m = GetModuleHandleA("kernelbase.dll");
    real_createfilew = (fn_createfilew)inline_hook(m ? (B *)GetProcAddress(m, "CreateFileW") : 0, (void *)trace_createfilew);
    LOG_BEGIN(); put_s("trace: watching"); put_s(real_access ? " _access" : " (not _access)"); put_s(real_cocreate ? " movie-players" : " (not movie players)");
    put_s(real_createfilew ? " avi-opens" : " (not file opens)"); log_end();
}

typedef U (__stdcall *fn_tick)(void);
static fn_tick real_tick;
U __stdcall hg_timeGetTime(void) {
    if (!real_tick) {
        init();
        real_tick = winmm ? (fn_tick)GetProcAddress(winmm, "timeGetTime") : 0;
        if (!real_tick) return GetTickCount();
    }
    trace_start();
    cwd_guard();
    return real_tick();
}

/* ---------------------------------------------------------------------------------------------- forwarding
   The rest of WINMM is passed on by jumping to the real function, found on first use. This is NOT done with export
   forwarders in the .def file ("name=WINMM.name"): some lld versions turn those into "_WINMM.name" on x86, a module
   that does not exist, and then HGSIM.DLL fails to load ("module not found") and the game drops back to the shell.
   Each trampoline keeps the caller's stack as it is, so the real stdcall function pops its own arguments. */
#define FORWARDED(X) \
    X(timeKillEvent) X(timeEndPeriod) X(timeGetDevCaps) X(timeBeginPeriod) X(timeSetEvent) \
    X(joyGetPosEx) X(joyGetDevCapsA) X(joyGetNumDevs) \
    X(mmioSetInfo) X(mmioSeek) X(mmioAdvance) X(mmioOpenA) X(mmioDescend) X(mmioRead) X(mmioAscend) X(mmioClose) \
    X(mmioGetInfo)

void *fwd_resolve(const char *name, void **slot) {          /* cdecl; called from the trampolines */
    if (!winmm) winmm = LoadLibraryA("winmm.dll");
    *slot = winmm ? GetProcAddress(winmm, name) : 0;
    return *slot;
}
#define TRAMPOLINE(n) \
    void *fwd_p_##n; \
    const char fwd_s_##n[] = #n; \
    __attribute__((naked, used)) void __stdcall fwd_##n(void) { \
        __asm__ volatile( \
            "movl _fwd_p_" #n ", %eax\n\t" \
            "testl %eax, %eax\n\t" \
            "jnz 1f\n\t" \
            "pushl $_fwd_p_" #n "\n\t" \
            "pushl $_fwd_s_" #n "\n\t" \
            "call _fwd_resolve\n\t" \
            "addl $8, %esp\n" \
            "1:\n\t" \
            "jmp *%eax"); \
    }
FORWARDED(TRAMPOLINE)

/* ---------------------------------------------------------------------------------------------- exports */
U __stdcall hg_mciSendCommandA(U id, U msg, U flags, U *p) {
    U r;
    init();
    if (!real_mci) return MCIERR_DEVICE_NOT_INSTALLED;
    if (!active) return real_mci(id, msg, flags, p);
    if (id == 0 && msg == MCI_SYSINFO && p && p[4] == MCI_DEVTYPE_CD_AUDIO) {                 /* {cb, ret, retsize, number, type} */
        if (flags & MCI_SYSINFO_QUANTITY) { *(U *)p[1] = 1; r = 0; }
        else if (flags & MCI_SYSINFO_NAME) { scopy((char *)p[1], "hgcd", p[2]); r = 0; }
        else r = MCIERR_UNSUPPORTED_FUNCTION;
    } else if (id == 0 && msg == MCI_OPEN && (flags & MCI_OPEN_TYPE) && p && p[2] && seqi((const char *)p[2], "hgcd")) {
        p[1] = FAKE_DEVICE; r = 0;
    } else if (id == FAKE_DEVICE) {
        r = emulate(msg, flags, p);
    } else {
        return real_mci(id, msg, flags, p);
    }
    LOG_BEGIN(); put_s("mci id="); put_x(id); put_s(" msg="); put_x(msg); put_s(" flags="); put_x(flags);
    if (p) { put_s(" p1="); put_x(p[1]); put_s(" p2="); put_x(p[2]); put_s(" p3="); put_x(p[3]); }
    put_s(" -> "); put_x(r); log_end();
    return r;
}
U __stdcall hg_mciGetErrorStringA(U err, char *buf, U len) {
    init();
    if (real_err) return real_err(err, buf, len);
    if (len) buf[0] = 0;
    return 0;
}
U __stdcall hg_auxGetNumDevs(void) { init(); return active ? 1 : real_auxn ? real_auxn() : 0; }
U __stdcall hg_auxGetDevCapsA(U dev, void *caps, U size) {
    init();
    if (!active) return real_auxcaps ? real_auxcaps(dev, caps, size) : 11 /* MMSYSERR_BADDEVICEID */;
    if (dev != 0) return 2;                                                  /* MMSYSERR_BADDEVICEID */
    { B *b = (B *)caps; U i; for (i = 0; i < size; i++) b[i] = 0;
      if (size >= 44) { scopy((char *)b + 8, "Heavy Gear music", 32); *(W *)(b + 40) = 1 /* AUXCAPS_CDAUDIO */; }
      if (size >= 48) *(U *)(b + 44) = 3; }                                  /* volume, left-right volume */
    return 0;
}
U __stdcall hg_auxGetVolume(U dev, U *vol) {
    init();
    if (!active) return real_auxget ? real_auxget(dev, vol) : 2;
    *vol = aux_vol; return 0;
}
U __stdcall hg_auxSetVolume(U dev, U vol) {
    init();
    if (!active) return real_auxset ? real_auxset(dev, vol) : 2;
    aux_vol = vol; apply_volume();
    LOG_BEGIN(); put_s("aux volume "); put_x(vol); log_end();
    return 0;
}

int __stdcall DllMain(HMOD h, U reason, void *reserved) {
    (void)reserved;
    if (reason == 1) self = h;
    else if (reason == 0) { el_close(); if (logf != (HANDLE)-1) CloseHandle(logf); }
    return 1;
}
