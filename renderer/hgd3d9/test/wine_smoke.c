/* wine_smoke.c - loads hgd3d9.dll under Wine, opens a device the way the game does (FirstDevice), draws a gradient fill, a
 * filled triangle and its outline for a few frames and lets the plugin save a frame (needs hgd3d9.dump and, to test the own-window path,
 * hgd3d9.window in the working directory). Prints the result to stdout. Freestanding, like the plugin. */
#include <stdint.h>
#define WINAPI __stdcall
__declspec(dllimport) void *WINAPI LoadLibraryA(const char *);
__declspec(dllimport) void *WINAPI GetProcAddress(void *, const char *);
__declspec(dllimport) void WINAPI ExitProcess(uint32_t);
__declspec(dllimport) void WINAPI Sleep(uint32_t);
__declspec(dllimport) void *WINAPI GetStdHandle(uint32_t);
__declspec(dllimport) int WINAPI WriteFile(void *, const void *, uint32_t, uint32_t *, void *);
__declspec(dllimport) void *WINAPI CreateWindowExA(uint32_t, const char *, const char *, uint32_t, int, int, int, int, void *, void *, void *, void *);
__declspec(dllimport) void *WINAPI SetActiveWindow(void *);
__declspec(dllimport) int WINAPI PeekMessageA(void *, void *, uint32_t, uint32_t, uint32_t);
__declspec(dllimport) int WINAPI DispatchMessageA(const void *);

typedef struct V { float x, y, w, oow; uint32_t light; uint8_t r, g, b, a; uint32_t fog; float u, v; } V;
typedef int (*f_first)(uint32_t *);
typedef int (*f_render)(uint32_t, void *, V *, uint32_t, uint32_t);
typedef int (*f_set)(uint32_t, uint32_t);
typedef void (*f_void)(void);
typedef uint32_t (*f_lock)(uint32_t *);

/* a fake texture the way the engine lays it out: block -> descriptor -> palette, then the pixels right after it */
static uint32_t g_tex_block[16], g_tex_desc[8], g_tex_data[256 + 64];
static void make_texture(void)
{
    uint32_t i; uint8_t *pix = (uint8_t *)&g_tex_data[256];
    for (i = 0; i < 256; i++) g_tex_data[i] = i < 16 ? ((i * 16) << 16) | (((15 - i) * 16) << 8) | 0x40 : 0;
    for (i = 0; i < 256; i++) pix[i] = (uint8_t)(((i >> 4) + (i & 15)) & 15);   /* 16x16 diagonal bands */
    g_tex_desc[0] = 16; g_tex_desc[1] = 16; g_tex_desc[2] = (uint32_t)(uintptr_t)pix; g_tex_desc[3] = (uint32_t)(uintptr_t)g_tex_data;
    g_tex_block[0] = (uint32_t)(uintptr_t)g_tex_desc;
}

static void say(const char *s) { uint32_t n = 0, w; while (s[n]) n++; WriteFile(GetStdHandle((uint32_t)-11), s, n, &w, 0); }

static V mk(float x, float y, float w, uint8_t r, uint8_t g, uint8_t b, uint8_t a)
{
    V v; v.x = x; v.y = y; v.w = w; v.oow = 1.0f / w; v.light = 255; v.r = r; v.g = g; v.b = b; v.a = a; v.fog = 0xff000000u; v.u = 0; v.v = 0;
    return v;
}

void mainCRTStartup(void)
{
    void *m = LoadLibraryA("hgd3d9.dll");
    uint32_t info[32] = {0}, ctx[8] = {1, 640, 480, 0, 0, 0, 639, 479}, i, stride = 0;
    union { float f; uint32_t u; } far_w;
    f_first first; f_render render; f_set setstate; f_void refresh, last; f_lock lock; f_void unlock;
    int r;
    if (!m) { say("cannot load hgd3d9.dll\r\n"); ExitProcess(2); }
    first = (f_first)GetProcAddress(m, "FirstDevice"); render = (f_render)GetProcAddress(m, "Render");
    setstate = (f_set)GetProcAddress(m, "SetState"); refresh = (f_void)GetProcAddress(m, "RefreshDisplay");
    last = (f_void)GetProcAddress(m, "LastDevice"); lock = (f_lock)GetProcAddress(m, "LockDisplay"); unlock = (f_void)GetProcAddress(m, "UnlockDisplay");
    if (!first || !render || !setstate || !refresh || !last || !lock || !unlock) { say("missing export\r\n"); ExitProcess(2); }
    /* a window to be "the game's" (used when hgd3d9.window is absent) */
    SetActiveWindow(CreateWindowExA(0, "STATIC", "smoke", 0x10C00000u, 10, 10, 656, 519, 0, 0, 0, 0));
    info[1] = 8; info[2] = 3; info[5] = 0x00ffffffu; far_w.f = 500000.0f; info[7] = far_w.u; info[15] = 640; info[16] = 480;   /* fog colour white */
    r = first(info);
    say(r == 0 ? "FirstDevice ok\r\n" : "FirstDevice FAILED\r\n");
    if (r) ExitProcess(1);
    make_texture();
    setstate(7, 0);
    setstate(1, 0x200000);                                 /* fog on, as the engine does */
    for (i = 0; i < 40; i++) {
        V fill[4], tri[3], c[3];
        uint16_t *hud; uint32_t k;
        { char msg[48]; while (PeekMessageA(msg, 0, 0, 0, 1)) DispatchMessageA(msg); }
        /* sky/ground fill: far plane (oow 0), a vertical gradient, opaque Gouraud (prim 15) */
        fill[0] = mk(0, 0, 1e30f, 10, 20, 90, 255); fill[1] = mk(639, 0, 1e30f, 10, 20, 90, 255);
        fill[2] = mk(639, 479, 1e30f, 200, 120, 40, 255); fill[3] = mk(0, 479, 1e30f, 200, 120, 40, 255);
        for (k = 0; k < 4; k++) fill[k].oow = 0.0f;
        fill[0].fog = fill[1].fog = 0xff000000u; fill[2].fog = fill[3].fog = 0;   /* top clear, bottom fully fogged */
        render(15, ctx, fill, 4, 0);
        setstate(0xc, 1);                                  /* depth clear, as the engine does after the fills */
        tri[0] = mk(120, 100, 1000, 255, 255, 255, 255); tri[1] = mk(520, 140, 1000, 255, 255, 255, 255); tri[2] = mk(300, 420, 1000, 255, 255, 255, 255);
        c[0] = tri[0]; c[1] = tri[1]; c[2] = tri[2];
        tri[0].r = 255; tri[0].g = 0; tri[0].b = 0; tri[1].r = 0; tri[1].g = 255; tri[1].b = 0; tri[2].r = 0; tri[2].g = 0; tri[2].b = 255;
        render(15, ctx, tri, 3, 0);                        /* a Gouraud triangle */
        c[0].r = 255; c[0].g = 255; c[0].b = 0; c[1] = c[0]; c[2] = c[0];
        c[0].x = tri[0].x; c[1].x = tri[1].x; c[2].x = tri[2].x; c[0].y = tri[0].y; c[1].y = tri[1].y; c[2].y = tri[2].y;
        c[0].w = c[1].w = c[2].w = 1000; c[0].oow = c[1].oow = c[2].oow = 1.0f / 1000.0f;
        render(18, ctx, c, 3, 0);                          /* its outline, on the same surface: must show */
        {   /* a textured quad (prim 1, lit): the texture path, with a frame-dependent light */
            V q[4]; q[0] = mk(40, 300, 800, 255, 255, 255, 255); q[1] = mk(240, 300, 800, 255, 255, 255, 255);
            q[2] = mk(240, 440, 800, 255, 255, 255, 255); q[3] = mk(40, 440, 800, 255, 255, 255, 255);
            q[0].u = 0; q[0].v = 0; q[1].u = 1; q[1].v = 0; q[2].u = 1; q[2].v = 1; q[3].u = 0; q[3].v = 1;
            for (k = 0; k < 4; k++) q[k].light = 120 + i * 3;
            render(1, ctx, q, 4, (uint32_t)(uintptr_t)g_tex_block);
        }
        hud = (uint16_t *)(uintptr_t)lock(&stride);        /* the 2D layer: a red rectangle */
        if (hud) for (k = 0; k < 640 * 30; k++) hud[(k / 640 + 20) * (stride / 2) + (k % 640)] = 0xF800;
        unlock();
        refresh();
        Sleep(16);
    }
    last();
    say("done\r\n");
    ExitProcess(0);
}

int _fltused = 1;
