/* selftest - drives hgcd.dll the way HGSIM.DLL does (device search, open, track starts, play range, polling, pause,
   resume, stop, volume) and checks the answers. Needs MUSIC\TRACK02.WAV and TRACK03.WAV, each about 2 seconds
   (test.sh makes them), found through the HGCD_MUSIC environment variable. It plays them on the default audio device.
   Freestanding, 32-bit, kernel32 only, like the DLL. Exit code 0 = all checks passed. */
typedef unsigned int U;
typedef unsigned short W;
typedef void *HANDLE;
typedef void *HMOD;
__declspec(dllimport) HMOD __stdcall LoadLibraryA(const char *);
__declspec(dllimport) void *__stdcall GetProcAddress(HMOD, const char *);
__declspec(dllimport) HANDLE __stdcall GetStdHandle(U);
__declspec(dllimport) int __stdcall WriteFile(HANDLE, const void *, U, U *, void *);
__declspec(dllimport) void __stdcall Sleep(U);
__declspec(dllimport) void __stdcall ExitProcess(U);
__declspec(dllimport) U __stdcall GetTickCount(void);
__declspec(dllimport) U __stdcall GetCurrentDirectoryA(U, char *);
__declspec(dllimport) int __stdcall SetCurrentDirectoryA(const char *);

typedef U (__stdcall *mci_t)(U, U, U, U *);
typedef U (__stdcall *aux0_t)(void);
typedef U (__stdcall *auxcaps_t)(U, void *, U);
typedef U (__stdcall *auxset_t)(U, U);
typedef U (__stdcall *tick_t)(void);
typedef U (__stdcall *arg1_t)(U);
typedef U (__stdcall *caps_t)(void *, U);

static HANDLE out;
static int failures;
static void say(const char *s) { U n = 0, w; while (s[n]) n++; WriteFile(out, s, n, &w, 0); }
static void hex(U v) { static const char h[] = "0123456789abcdef"; char t[12]; int n = 0; t[n++] = '0'; t[n++] = 'x';
    for (int i = 28; i >= 0; i -= 4) t[n++] = h[v >> i & 15]; t[n++] = 0; say(t); }
static void check(const char *name, int cond, U val) {
    say(cond ? "ok   " : "FAIL "); say(name); say("  "); hex(val); say("\r\n"); if (!cond) failures++;
}
static mci_t mci;
static U dev;
static U status(U item, U flags, U track) { U s[4] = { 0, 0, item, track }; mci(dev, 0x814, flags, s); return s[1]; }
static U mode(void) { return status(4, 0x100, 0); }

void mainCRTStartup(void) {
    HMOD h = LoadLibraryA("hgcd.dll");
    out = GetStdHandle((U)-11);
    if (!h) { say("cannot load hgcd.dll\r\n"); ExitProcess(2); }
    mci = (mci_t)GetProcAddress(h, "mciSendCommandA");
    aux0_t auxn = (aux0_t)GetProcAddress(h, "auxGetNumDevs");
    auxcaps_t caps = (auxcaps_t)GetProcAddress(h, "auxGetDevCapsA");
    auxset_t setvol = (auxset_t)GetProcAddress(h, "auxSetVolume");
    tick_t timeGetTime = (tick_t)GetProcAddress(h, "timeGetTime");
    if (!mci || !auxn || !caps || !setvol || !timeGetTime) { say("missing export\r\n"); ExitProcess(2); }

    U t0 = timeGetTime(); Sleep(60); U dt = timeGetTime() - t0;
    check("timeGetTime is forwarded to the real WINMM", dt >= 30 && dt < 500, dt);
    arg1_t begin = (arg1_t)GetProcAddress(h, "timeBeginPeriod"), end = (arg1_t)GetProcAddress(h, "timeEndPeriod");
    caps_t devcaps = (caps_t)GetProcAddress(h, "timeGetDevCaps");
    unsigned char tc[8];
    U sp0, sp1;
    __asm__ volatile("movl %%esp, %0" : "=r"(sp0));
    U r1 = begin(1), r2 = devcaps(tc, 8), r3 = end(1);
    __asm__ volatile("movl %%esp, %0" : "=r"(sp1));
    {   /* the working folder: moved away, it must be put back by the next timeGetTime */
        char home[300], now[300]; int same = 1;
        GetCurrentDirectoryA(300, home);
        SetCurrentDirectoryA("C:/");
        Sleep(250);
        timeGetTime();
        GetCurrentDirectoryA(300, now);
        for (int i = 0; home[i] || now[i]; i++) if (home[i] != now[i]) same = 0;
        check("the working folder is put back after something moves it", same, same);
    }
    check("calls with arguments go through (timeBeginPeriod, timeGetDevCaps, timeEndPeriod)", r1 == 0 && r2 == 0 && r3 == 0, r1 | r2 | r3);
    check("the stack is balanced after them", sp0 == sp1, sp1 - sp0);

    unsigned char c[48];
    U r = caps(0, c, 48);
    check("one aux device", auxn() == 1, auxn());
    check("it is a CD audio device", r == 0 && *(W *)(c + 40) == 1, *(W *)(c + 40));

    U sys[5] = { 0, 0, 4, 0, 0x204 }, qty = 0;
    sys[1] = (U)&qty;
    check("sysinfo quantity = 1", mci(0, 0x810, 0x100, sys) == 0 && qty == 1, qty);
    char name[64]; sys[1] = (U)name; sys[2] = 64;
    check("sysinfo name is hgcd", mci(0, 0x810, 0x400, sys) == 0 && name[0] == 'h' && name[3] == 'd' && !name[4], 0);
    U op[5] = { 0, 0, (U)name, 0, 0 };
    check("open", mci(0, 0x803, 0x2000, op) == 0 && op[1] != 0, op[1]);
    dev = op[1];
    U tf[3] = { 0, 0, 10 };
    check("set time format", mci(dev, 0x80d, 0x400, tf) == 0, 0);
    check("number of tracks = 3", status(3, 0x100, 0) == 3, status(3, 0x100, 0));
    U s2 = status(2, 0x110, 2), s3 = status(2, 0x110, 3);
    check("start of track 2", (s2 & 0xff) == 2, s2);
    check("start of track 3", (s3 & 0xff) == 3, s3);
    check("stopped before playing", mode() == 0x20d, mode());
    check("set volume", setvol(0, 0x80008000) == 0, 0);

    U pl[3] = { 0, s2, s3 }, z[3] = { 0, 0, 0 };
    check("play track 2 only", mci(dev, 0x806, 4 | 8, pl) == 0, 0);
    Sleep(600);
    check("mode playing", mode() == 0x20e, mode());
    U pos = status(2, 0x100, 0);
    check("position: track 2, at the start", (pos & 0xff) == 2 && (pos >> 8 & 0xff) == 0, pos);
    check("pause", mci(dev, 0x809, 0, z) == 0, 0);
    check("mode paused", mode() == 0x211, mode());
    check("resume", mci(dev, 0x855, 0, z) == 0, 0);
    check("mode playing again", mode() == 0x20e, mode());
    Sleep(2600);
    check("range over: stopped", mode() == 0x20d, mode());

    U from[3] = { 0, s2, 0 };
    check("play track 2 to the end of the disc", mci(dev, 0x806, 4, from) == 0, 0);
    Sleep(2600);
    pos = status(2, 0x100, 0);
    check("moved on to track 3", (pos & 0xff) == 3, pos);
    check("still playing", mode() == 0x20e, mode());
    check("stop", mci(dev, 0x808, 0, z) == 0 && mode() == 0x20d, mode());
    check("close", mci(dev, 0x804, 0, z) == 0, 0);
    say(failures ? "FAILURES\r\n" : "ALL OK\r\n");
    ExitProcess(failures ? 1 : 0);
}
