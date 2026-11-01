/* hgd3d9.c - the Heavy Gear renderer plugin. It exports the functions the game's loader looks up
 * (docs/research/renderer-interface.md), turns each Render call into HgVertex polygons and hands them to a backend.
 * Freestanding (no CRT); cdecl, as the original plugins are. Reports plugin id 2 so the shell lists it next to the 3Dfx
 * plugin and picks it by file name. */
#include <stddef.h>
#include <stdint.h>
#include "backend.h"
#include "convert.h"
#include "texcache.h"
#define HG_CAP_RECORDER
#include "capture.h"

void *memset(void *, int, size_t);   /* rt.c */

#define EXPORT __declspec(dllexport)
#define WINAPI __stdcall

__declspec(dllimport) void *WINAPI CreateFileA(const char *, uint32_t, uint32_t, void *, uint32_t, uint32_t, void *);
__declspec(dllimport) int WINAPI WriteFile(void *, const void *, uint32_t, uint32_t *, void *);
__declspec(dllimport) int WINAPI CloseHandle(void *);
__declspec(dllimport) int WINAPI ReadFile(void *, void *, uint32_t, uint32_t *, void *);
__declspec(dllimport) uint32_t WINAPI SetFilePointer(void *, int, int *, uint32_t);
__declspec(dllimport) void *WINAPI GetActiveWindow(void);
__declspec(dllimport) void *WINAPI GetModuleHandleA(const char *);
__declspec(dllimport) uint32_t WINAPI GetCurrentProcessId(void);
__declspec(dllimport) int WINAPI EnumWindows(int (WINAPI *)(void *, intptr_t), intptr_t);
__declspec(dllimport) uint32_t WINAPI GetWindowThreadProcessId(void *, uint32_t *);
__declspec(dllimport) int WINAPI GetClassNameA(void *, char *, int);
__declspec(dllimport) int WINAPI GetWindowTextA(void *, char *, int);
__declspec(dllimport) int WINAPI GetWindowRect(void *, int *);
__declspec(dllimport) int WINAPI IsWindowVisible(void *);
__declspec(dllimport) int WINAPI SetWindowPos(void *, void *, int, int, int, int, uint32_t);
__declspec(dllimport) uint32_t WINAPI RegisterClassA(const void *);
__declspec(dllimport) void *WINAPI CreateWindowExA(uint32_t, const char *, const char *, uint32_t, int, int, int, int, void *, void *, void *, void *);
__declspec(dllimport) int WINAPI ShowWindow(void *, int);
__declspec(dllimport) int WINAPI DestroyWindow(void *);
__declspec(dllimport) int WINAPI AdjustWindowRect(int *, uint32_t, int);
__declspec(dllimport) intptr_t WINAPI DefWindowProcA(void *, uint32_t, uintptr_t, intptr_t);
__declspec(dllimport) int WINAPI IsBadReadPtr(const void *, uint32_t);
__declspec(dllimport) void *WINAPI LoadLibraryA(const char *);
__declspec(dllimport) void *WINAPI GetProcAddress(void *, const char *);
__declspec(dllimport) int WINAPI QueryPerformanceCounter(int64_t *);
__declspec(dllimport) int WINAPI QueryPerformanceFrequency(int64_t *);

#ifndef HG_BACKEND
#define HG_BACKEND hg_backend_d3d9
#endif
static const HgBackend *g_be = &HG_BACKEND;

#define PLUGIN_ID 2
#define PITCH (HG_GAME_W * 2)     /* bytes per row of the RGB565 2D layer */
#define MAX_POLY 16

/* ---- log: opened on first use and appended to, because the shell loads this DLL again to probe it (after a mission, for
 * one) and a truncating open in DllMain wiped the session's log ------------------------------------------------------- */
static void *g_log;
static int g_log_tried;
static void put(const char *s)
{
    uint32_t n = 0, w;
    if (!g_log_tried) {
        g_log_tried = 1;
        g_log = CreateFileA("hgd3d9.log", 0x40000000, 3, 0, 4, 0x80, 0);   /* OPEN_ALWAYS */
        if (g_log == (void *)-1) g_log = 0; else SetFilePointer(g_log, 0, 0, 2);
    }
    while (s[n]) n++;
    if (g_log) WriteFile(g_log, s, n, &w, 0);
}
static void putdec(uint32_t v) { char b[12]; int i = 11; b[i] = 0; do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v); put(b + i); }

void hg_log(const char *s) { put(s); }
void hg_log_dec(uint32_t v) { putdec(v); }
void hg_log_hex(uint32_t v)
{
    char b[11] = "0x00000000"; int i;
    for (i = 0; i < 8; i++) b[9 - i] = "0123456789abcdef"[(v >> (4 * i)) & 15];
    put(b);
}
int hg_readable(const void *p, uint32_t bytes) { return (uintptr_t)p > 0x10000 && !IsBadReadPtr(p, bytes); }
int hg_write_file(const char *path, const void *data, uint32_t bytes)
{
    uint32_t w = 0; int ok;
    void *f = CreateFileA(path, 0x40000000, 0, 0, 2, 0x80, 0);
    if (f == (void *)-1) return 1;
    ok = WriteFile(f, data, bytes, &w, 0) && w == bytes;
    CloseHandle(f);
    return ok ? 0 : 1;
}

/* ---- state -------------------------------------------------------------------------------------------------- */
static uint32_t g_frame, g_renders, g_locks, g_skipped, g_notex, g_noop, g_prim[32];
/* Effect bursts: when a frame has many effect-type primitives (blended, unlit or point primitives), save a screenshot and log
 * the frame's primitive mix, so what the effects look like can be checked. Needs hgd3d9.dump. */
static uint32_t g_fprim[32], g_fx_dumps, g_fx_last, g_vlog[32];
/* Low light: fog switching off marks it. For a while afterwards, screenshots and the primitive mix are saved (needs hgd3d9.dump). */
static uint32_t g_ll_start, g_ll_vlog[32];
/* Slivers: polygons less than 1.6 pixels tall and wider than 20, logged with their primitive, depth and fog, to see what produces the thin
 * horizontal lines at the horizon. Needs hgd3d9.dump. */
static uint32_t g_sliver_logged;
static uint32_t g_fog, g_state5, g_state7 = 1, g_depth_mode, g_flags;
static float    g_far_w = HG_DEFAULT_FAR_W;
static int      g_ready, g_locked, g_dump;   /* g_dump: hgd3d9.dump exists, so save a few frames as BMP */
static uint8_t  g_overlay[PITCH * HG_GAME_H];   /* the 2D layer, RGB565; cleared to 0 each frame */

/* Frame timing, to find stalls. */
static int64_t  g_qpf, g_last_qpc, g_sum_qpc;
static int64_t  g_t_render, g_t_overlay, g_t_present, g_s_render, g_s_overlay, g_s_present;   /* time in our code, this frame and summed */
static int64_t  g_t_setstate, g_t_lock, g_t_refresh, g_s_setstate, g_s_lock, g_s_refresh;        /* the other exports */
/* The frame's timeline, from our own calls: engine start of frame (after the previous present) to the first Render, first to last
 * Render (engine transforms plus our drawing), and last Render to RefreshDisplay (the 2D layer, locks). */
static int64_t  g_frame_start, g_first_render, g_last_render_end;
static int64_t  g_seg_a, g_seg_b, g_seg_c, g_s_a, g_s_b, g_s_c;
static uint32_t g_slow, g_prev_renders, g_prev_creates, g_prev_updates;

/* What each primitive does in the v1.2 3Dfx plugin's Render switch [CODE, 1.2 plugin, function at 0x10001590]. The keyed flag is
 * the argument Render passes down to the texture setup; the key colour is palette[desc[4]]. */
enum { K_NONE, K_TEX, K_FILL, K_FILL_CONST, K_OUTLINE, K_POINTS };
typedef struct PrimInfo { uint8_t kind, keyed, blend, lit; } PrimInfo;
static const PrimInfo g_info[21] = {
    /*  0 */ { K_TEX, 0, 0, 1 }, /*  1 */ { K_TEX, 0, 0, 1 }, /*  2 */ { K_TEX, 0, 0, 1 },     /* lit textured, opaque */
    /*  3 */ { K_TEX, 1, 0, 1 }, /*  4 */ { K_TEX, 1, 0, 1 },                                   /* lit textured, keyed, opaque */
    /*  5 */ { K_NONE, 0, 0, 0 }, /* 6 */ { K_NONE, 0, 0, 0 },                                  /* draw nothing */
    /*  7 */ { K_TEX, 1, 1, 0 }, /*  8 */ { K_TEX, 1, 1, 0 },                                   /* unlit textured, keyed, texture alpha */
    /*  9 */ { K_TEX, 0, 0, 0 },                                                                 /* unlit textured, opaque */
    /* 10 */ { K_TEX, 1, 0, 0 }, /* 11 */ { K_TEX, 1, 0, 0 },                                   /* unlit textured, keyed, opaque */
    /* 12 */ { K_TEX, 1, 1, 0 }, /* 13 */ { K_TEX, 1, 1, 0 },                                   /* unlit textured, keyed, texture alpha */
    /* 14 */ { K_FILL_CONST, 0, 0, 0 },                                                          /* one constant colour (arg+4) */
    /* 15 */ { K_FILL, 0, 0, 1 },                                                                /* Gouraud, opaque */
    /* 16 */ { K_FILL, 0, 1, 1 }, /* 17 */ { K_FILL, 0, 1, 1 },                                  /* Gouraud, blended with vertex alpha */
    /* 18 */ { K_OUTLINE, 0, 0, 1 }, /* 19 */ { K_OUTLINE, 0, 0, 1 },                           /* polygon outline: the wireframes */
    /* 20 */ { K_POINTS, 0, 0, 0 }                                                               /* points, constant colour (arg+4) */
};

/* ---- tee mode: with a file hgd3d9.tee in the game folder, the real 3Dfx plugin is loaded as well and every call goes to
 * both paths. The engine gets the real plugin's answers, so it behaves as it does natively, and each path is timed on the
 * same frames. The 2D layer is written by the engine into our buffer; on unlock the pixels it touched are copied into the
 * real plugin's buffer too. --------------------------------------------------------------------------------------------- */
typedef int      (*fn_first)(uint32_t *);
typedef void     (*fn_void)(void);
typedef int      (*fn_int0)(void);
typedef int      (*fn_render)(uint32_t, uint32_t *, GameVertex *, uint32_t, uint32_t);
typedef int      (*fn_u2)(uint32_t, uint32_t);
typedef int      (*fn_u1)(uint32_t);
typedef uint32_t (*fn_lock)(uint32_t *);
typedef uint32_t (*fn_caps)(void);
static struct RealPlugin {
    fn_first first; fn_void last, unlock, refresh, luma; fn_int0 renderrefresh, restore, lost;
    fn_render render, rendernoclip; fn_u2 setstate, palette, update; fn_u1 preload; fn_lock lock; fn_caps caps;
} g_real;
static int      g_tee;
static char     g_shot_name[32];               /* a screenshot requested by the replay tool, taken in the next RefreshDisplay */
static int      g_cap;                         /* hgd3d9.capture: record every call to hgd3d9.cap (capture.h) */
/* hgd3d9.p17modes: cycle how prims 16 and 17 (the blended fills: the glow fans) are drawn, 120 frames each, to find what matches the
 * native picture. 0 alpha = 255 - fog byte, fog on, RGB (the current rule); 1 alpha byte, no fog, RGB; 2 alpha byte, no fog, BGR;
 * 3 alpha byte, fog on, RGB; 4 alpha = 255 - fog byte, fog on, BGR. */
static int      g_p17modes;
static uint32_t g_p17mode;
static int      g_p17fixed;                    /* a fixed mode was asked for with hgd3d9.p17modeN */
static int      g_sky_painter;                 /* hgd3d9.skypainter (experiment): draws before the frame's first depth clear ignore depth */
static int      g_sky_done;                    /* the first SetState 0xc of this frame has happened */
static int      g_sky2skip;                    /* prim 2 draws before the first depth clear (the horizon haze quad) are not drawn; hgd3d9.sky2draw draws them */
static int      g_noclip;                      /* hgd3d9.noclip (debugging): fans are not clipped to the view */
static float    g_glow_bias = 0.03f;                   /* 1/w of the blended fills (16, 17) is scaled by 1 + this (default 0.03; hgd3d9.glowbiasN sets N * 0.01): glow pools lie on the ground and fight it for depth */
static int      g_rhw_depth;                   /* depth = 1 - 1/w unless hgd3d9.zlinear exists */
static int      g_odepth;                      /* outlines: 3 (default) test only with a 1000x bias; 0 ignore depth; 1 test only; 2 test and write; hgd3d9.odepthN selects */
static float    g_spr_opacity = 1.0f;          /* hgd3d9.opacN scales the opacity of blended sprites: N = 9, 8, 7, 6, 5 for 0.9 .. 0.5 */
static float    g_fillw_ext = -1.0f;           /* default: every opaque fill (hgd3d9.fillwsmall restores the old limits: huge or distant fills only) */         /* extent in pixels above which a fill counts as a huge ground polygon */
static float    g_fillw_far = -1.0f;                  /* mean w above which a fill is distant terrain, not a mech */
static int      g_fillw = 1;                   /* distant or huge opaque fills take 1/w from the vertex's w word instead of the 1/w word, which is stale on some of them; hgd3d9.nofillw turns it off */
static int      g_fillnowrite = 0;             /* opaque fills (the black hidden-line fills of low light) test depth but do not write it, as on the 3Dfx: they hide lines by painting over them in draw order (low-light error against native 0.41 -> 0.08) */
static int      g_hidemodels = 1;              /* opaque fills write true depth (background fills excepted); terrain outlines (0x580000) keep the native rule, every other outline (gears, rocks, damage) is occluded by that depth, so a gear behind a hill shows only what is above its edge. hgd3d9.nativefills: the pure native rule (fills write nothing; whole gears show through hills) */
static int      g_hidefar;                     /* hgd3d9.hidefar: the stricter occlusion instead: fills write depth and outlines test against it (25% bias), so a gear behind a hill is hidden; the cost is lines native shows */
static int      g_nosort;                      /* hgd3d9.nosort: blended sprites are drawn in the engine's order */
static int      g_nodrawbias = 1;              /* no per-draw depth nudge (the default); hgd3d9.drawbias turns it on: it changes which ties win, and with it how big the shadows are */
static int      g_glowlift = 1;                /* hgd3d9.glowtrue: glow fans keep their true depth */
static int      g_lights = 1, g_lights_ok = 1;      /* point lights instead of the flat glow (see flush_light); hgd3d9.nolights, lightrN, lightampN (N * 0.25) */
static float    g_light_rscale = 1.0f, g_light_amp = 1.0f;
static int      g_nosprite2;                   /* hgd3d9.sprite1: blended sprites write depth like everything else (the old behaviour) */
static uint32_t g_draw_idx;                    /* draws so far this frame: each one is a little nearer than the last, so depth ties go to the later draw as on the Voodoo */
static uint32_t g_skip;                        /* bit N: hgd3d9.skipNN exists, so primitive N is not drawn */
static int      g_glownowrite;                 /* the blended fills (16, 17) test depth but do not write it; hgd3d9.glowwrite restores writing */
static int      g_mipmode = 3;                 /* what set_mipmaps gets when mipmaps are forced on: 3 = mipmaps with LOD bias -1 (best on both captures); hgd3d9.biasN gives 1 + N */
static int      g_forcemips;                   /* mipmapping always on, whatever SetState 7 says (the engine sends 0); hgd3d9.nomips follows SetState 7 instead */
static int      g_wquant;                      /* hgd3d9.wquant: quantise depth like the Voodoo W-buffer */
static int      g_timelapse;                   /* hgd3d9.timelapse: save a frame (and the native one in tee mode) every 90 frames */
static uint32_t g_tl_count;
static int      g_ab;                          /* hgd3d9.ab: alternate our drawing on and off every 240 frames (needs tee) */
static int      g_on = 1;                      /* whether our drawing is on for the current frame */
static uint8_t *g_real_buf;                    /* the real plugin's locked buffer for this frame, or NULL */
static uint32_t g_real_stride;
static int64_t  g_n_render, g_n_setstate, g_n_lock, g_n_refresh, g_sn_render, g_sn_setstate, g_sn_lock, g_sn_refresh;   /* native path time */

static int tee_load(void)
{
    void *m = LoadLibraryA("PLUGIN\\3dfxgear.dll");
    if (!m) { put("tee: cannot load PLUGIN\\3dfxgear.dll\r\n"); return 0; }
    g_real.first = (fn_first)GetProcAddress(m, "FirstDevice");
    g_real.last = (fn_void)GetProcAddress(m, "LastDevice");
    g_real.renderrefresh = (fn_int0)GetProcAddress(m, "RenderRefresh");
    g_real.render = (fn_render)GetProcAddress(m, "Render");
    g_real.rendernoclip = (fn_render)GetProcAddress(m, "RenderNoClip");
    g_real.setstate = (fn_u2)GetProcAddress(m, "SetState");
    g_real.palette = (fn_u2)GetProcAddress(m, "SetTexturePalette");
    g_real.lock = (fn_lock)GetProcAddress(m, "LockDisplay");
    g_real.unlock = (fn_void)GetProcAddress(m, "UnlockDisplay");
    g_real.refresh = (fn_void)GetProcAddress(m, "RefreshDisplay");
    g_real.preload = (fn_u1)GetProcAddress(m, "PreloadTexture");
    g_real.update = (fn_u2)GetProcAddress(m, "UpdateTexture");
    g_real.restore = (fn_int0)GetProcAddress(m, "RestoreDevice");
    g_real.lost = (fn_int0)GetProcAddress(m, "LostDeviceDisplay");
    g_real.caps = (fn_caps)GetProcAddress(m, "GetSocketCaps");
    g_real.luma = (fn_void)GetProcAddress(m, "SetLumaTable");
    if (!g_real.first || !g_real.render || !g_real.rendernoclip || !g_real.setstate || !g_real.lock || !g_real.unlock ||
        !g_real.refresh || !g_real.last || !g_real.palette || !g_real.renderrefresh || !g_real.preload || !g_real.update ||
        !g_real.restore || !g_real.lost || !g_real.caps || !g_real.luma) { put("tee: the real plugin lacks an export\r\n"); return 0; }
    return 1;
}

/* hgd3d9.window: draw into a window of our own (640x480 client, to the right of the game's) instead of the game's window, so that
 * in tee mode the two outputs do not cover each other. The window needs a desktop wider than 640 pixels to be visible
 * (HG_RES=1320x520 with run-heavygear.sh). Its messages are pumped by the game's own loop, as it is created on the same thread. */
static void *g_own_wnd;
static void *make_own_window(void)
{
    struct { uint32_t style; void *proc; int cls, wnd; void *inst, *icon, *cursor, *brush; const char *menu, *name; } wc;
    int r[4] = { 0, 0, HG_GAME_W, HG_GAME_H };
    const uint32_t style = 0x00C00000u | 0x00080000u | 0x10000000u;   /* WS_CAPTION | WS_SYSMENU | WS_VISIBLE */
    void *w;
    wc.style = 0; wc.proc = (void *)DefWindowProcA; wc.cls = 0; wc.wnd = 0; wc.inst = GetModuleHandleA(0);
    wc.icon = 0; wc.cursor = 0; wc.brush = 0; wc.menu = 0; wc.name = "HGRenderOut";
    RegisterClassA(&wc);                                              /* fails harmlessly if already registered */
    AdjustWindowRect(r, style, 0);
    w = CreateWindowExA(0, "HGRenderOut", "Direct3D 9 renderer", style, 660, 0, r[2] - r[0], r[3] - r[1], 0, 0, wc.inst, 0);
    if (w) ShowWindow(w, 5);
    return w;
}

/* Tee mode with our own window: the real plugin's (Glide) window is created inside its FirstDevice. It can end up behind the game's
 * own blank popup, so list this process's windows and send the game's window to the back (without activating anything). */
static void *g_game_wnd;
static int WINAPI window_cb(void *w, intptr_t arg)
{
    uint32_t pid = 0; char cls[64] = "", title[64] = ""; int r[4] = { 0, 0, 0, 0 };
    GetWindowThreadProcessId(w, &pid);
    if (pid != GetCurrentProcessId()) return 1;
    GetClassNameA(w, cls, 63); GetWindowTextA(w, title, 63); GetWindowRect(w, r);
    if (arg == 1) {
        put("  window "); hg_log_hex((uint32_t)(uintptr_t)w); put(IsWindowVisible(w) ? " visible" : " hidden"); put(" class '"); put(cls);
        put("' title '"); put(title); put("' rect "); putdec((uint32_t)r[0]); put(","); putdec((uint32_t)r[1]); put(","); putdec((uint32_t)r[2]); put(","); putdec((uint32_t)r[3]); put("\r\n");
    }
    return 1;
}
static void survey_windows(const char *when) { put("windows ("); put(when); put("):\r\n"); EnumWindows(window_cb, 1); }
static void arrange_windows(void)
{
    if (g_game_wnd && g_own_wnd) SetWindowPos(g_game_wnd, (void *)1 /* HWND_BOTTOM */, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);   /* NOSIZE | NOMOVE | NOACTIVATE */
}

/* Tee mode: at the moments we save our own frame, ask the Glide proxy to save the native back buffer too (hgnat_NNNN.bmp), so the two
 * pictures of the same frame can be compared. Called just before the real plugin's RefreshDisplay swaps. */
static int g_nat_want, g_cap_ref;
static uint32_t g_odd_prim, g_burst_refs, g_last_burst = 0;   /* effect frames get reference pictures too (capture mode) */
static void native_shot(void)
{
    typedef uint32_t (WINAPI *cap_fn)(const char *);
    void *m = GetModuleHandleA("glide2x.dll");
    cap_fn cap = m ? (cap_fn)GetProcAddress(m, "hgCaptureNative") : (cap_fn)0;
    char name[24] = "hgnat_0000.bmp"; uint32_t f = g_frame, k;
    for (k = 0; k < 4; k++) { name[9 - k] = (char)('0' + f % 10); f /= 10; }
    put("native capture "); put(name);
    put(cap ? (cap(name) ? " ok\r\n" : " failed\r\n") : " (the Glide proxy has no hgCaptureNative)\r\n");
}

static void summary(const char *when)
{
    uint32_t i;
    put("hgd3d9 "); put(when); put(" frame "); putdec(g_frame); put(" renders "); putdec(g_renders);
    put(" locks "); putdec(g_locks); put(" skipped "); putdec(g_skipped);
    put(" noop "); putdec(g_noop); put(" notex "); putdec(g_notex); put(" textures "); putdec(hg_texcache_count());
    put(" fog "); putdec(g_fog); put(" state5 "); putdec(g_state5); put(" state7 "); putdec(g_state7);
    put(" depthmode "); putdec(g_depth_mode); put(" slow "); putdec(g_slow); put(" prims");
    for (i = 0; i < 32; i++) if (g_prim[i]) { put(" p"); putdec(i); put("="); putdec(g_prim[i]); }
    put("\r\n");
}

int WINAPI DllMain(void *h, uint32_t reason, void *r)
{
    (void)h; (void)r;
    if (reason == 0 && g_ready) summary("exit");     /* only a real session; the shell's probe loads and frees without FirstDevice */
    return 1;
}

/* ---- the plugin API ----------------------------------------------------------------------------------------- */
EXPORT int GetFuncDesc(char *kind, uint32_t *id, char *name)
{
    const char *k = "RASTER", *n = "Direct3D 9";
    int i;
    for (i = 0; k[i]; i++) kind[i] = k[i];
    kind[i] = 0;
    *id = PLUGIN_ID;
    if (name) { for (i = 0; n[i]; i++) name[i] = n[i]; name[i] = 0; }
    return 0;
}
EXPORT int CheckFunc(uint32_t arg) { (void)arg; return 1; }
EXPORT int GetNumDevice(uint32_t arg) { (void)arg; return 1; }
EXPORT uint32_t GetSocketCaps(void) { return g_tee ? g_real.caps() : (g_flags & 3); }   /* bit 0 depth buffer, bit 1 fog, as FirstDevice was asked */
EXPORT void SetLumaTable(void) { if (g_tee) g_real.luma(); }

EXPORT int FirstDevice(uint32_t *info)
{
    HgInitParams p;
    union { uint32_t u; float f; } far_w;
    void *d;
    g_flags = info[2];
    g_fog = (g_flags & 2) != 0;              /* the 3Dfx plugin's FirstDevice calls grFogMode(1) when this bit is set: fog is on until the engine says otherwise */
    far_w.u = info[7];                       /* DeviceInfo+0x1c: 500000.0 seen */
    if (far_w.f > 0.0f) g_far_w = far_w.f;
    d = CreateFileA("hgd3d9.dump", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { g_dump = 1; CloseHandle(d); }
    d = CreateFileA("hgd3d9.tee", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_tee = tee_load(); }
    d = CreateFileA("hgd3d9.capture", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_cap = hg_cap_open("hgd3d9.cap") == 0; if (g_cap) hg_cap_init(info, hg_readable(info, 128) ? 32 : 17); }
    d = CreateFileA("hgd3d9.p17modes", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_p17modes = 1; }
    { static const char *fixed[5] = { "hgd3d9.p17mode0", "hgd3d9.p17mode1", "hgd3d9.p17mode2", "hgd3d9.p17mode3", "hgd3d9.p17mode4" }; uint32_t k;
      for (k = 0; k < 5; k++) {          /* hgd3d9.p17modeN: use mode N for the whole run (the replay tool tries each) */
          d = CreateFileA(fixed[k], 0x80000000, 3, 0, 3, 0x80, 0);
          if (d != (void *)-1) { CloseHandle(d); g_p17modes = 1; g_p17fixed = 1; g_p17mode = k; }
      } }
    { char nm[20] = "hgd3d9.skip00"; uint32_t k;      /* hgd3d9.skipN: do not draw primitive N (a debugging aid for the replay) */
      for (k = 0; k < 21; k++) {
          nm[13] = (char)('0' + k / 10); nm[14] = (char)('0' + k % 10);
          d = CreateFileA(nm, 0x80000000, 3, 0, 3, 0x80, 0);
          if (d != (void *)-1) { CloseHandle(d); g_skip |= 1u << k; }
      } }
    d = CreateFileA("hgd3d9.skypainter", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_sky_painter = 1; }
    g_sky2skip = 1;                           /* the horizon haze quad (prim 2, w = 1, before the first depth clear) never shows natively: night frames show black there */
    d = CreateFileA("hgd3d9.sky2draw", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_sky2skip = 0; }
    d = CreateFileA("hgd3d9.noclip", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_noclip = 1; }
    { static const char *pn[6] = { "hgd3d9.glowpct10", "hgd3d9.glowpct20", "hgd3d9.glowpct35", "hgd3d9.glowpct50", "hgd3d9.glowpct100", "hgd3d9.glowpct200" }; static const float pv[6] = { 0.1f, 0.2f, 0.35f, 0.5f, 1.0f, 2.0f }; uint32_t k;
      for (k = 0; k < 6; k++) { d = CreateFileA(pn[k], 0x80000000, 3, 0, 3, 0x80, 0); if (d != (void *)-1) { CloseHandle(d); g_glow_bias = pv[k]; } } }
    { char nm[20] = "hgd3d9.glowbias0"; uint32_t k;
      for (k = 1; k <= 9; k++) { nm[17] = (char)('0' + k); d = CreateFileA(nm, 0x80000000, 3, 0, 3, 0x80, 0); if (d != (void *)-1) { CloseHandle(d); g_glow_bias = 0.01f * (float)k; } } }
    g_rhw_depth = 1;                          /* depth = 1 - 1/w: exact when D3D interpolates it across a big polygon (w/far is not) */
    d = CreateFileA("hgd3d9.zlinear", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_rhw_depth = 0; }
    g_odepth = 1;                             /* outlines test depth without writing it, 25% nearer in 1/w; with true fill depths (fillw) this hides far gears and rocks behind hills without the flicker */
    { static const char *on[4] = { "hgd3d9.odepth0", "hgd3d9.odepth1", "hgd3d9.odepth2", "hgd3d9.odepth3" }; uint32_t k;
      for (k = 0; k < 4; k++) { d = CreateFileA(on[k], 0x80000000, 3, 0, 3, 0x80, 0); if (d != (void *)-1) { CloseHandle(d); g_odepth = (int)k; } } }
    d = CreateFileA("hgd3d9.drawbias", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_nodrawbias = 0; }
    d = CreateFileA("hgd3d9.sprite1", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_nosprite2 = 1; }
    { char on[16] = "hgd3d9.opac5"; int k; for (k = 5; k <= 9; k++) { on[13] = (char)('0' + k); d = CreateFileA(on, 0x80000000, 3, 0, 3, 0x80, 0); if (d != (void *)-1) { CloseHandle(d); g_spr_opacity = 0.1f * (float)k; } } }
    d = CreateFileA("hgd3d9.fillwsmall", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_fillw_ext = 3000.0f; g_fillw_far = 20000.0f; }
    d = CreateFileA("hgd3d9.nofillw", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_fillw = 0; }
    d = CreateFileA("hgd3d9.nativefills", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_hidemodels = 0; g_fillnowrite = 1; g_fillw_ext = 3000.0f; g_fillw_far = 20000.0f; }
    d = CreateFileA("hgd3d9.hidefar", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_hidefar = 1; g_fillnowrite = 0; g_fillw_ext = -1.0f; g_fillw_far = -1.0f; }
    hg_texcache_set_black_key(1);             /* a keyed texture whose key index lies past its palette: black is the key (the explosion's transparent square) */
    d = CreateFileA("hgd3d9.noblackkey", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); hg_texcache_set_black_key(0); }
    { char bn[16] = "hgd3d9.bleed0"; int q; void *hb;
      for (q = 1; q <= 9; q++) { bn[14] = (char)('0' + q); hb = CreateFileA(bn, 0x80000000, 3, 0, 3, 0x80, 0); if (hb != (void *)-1) { CloseHandle(hb); hg_texcache_set_bleed_params((uint32_t)(q * 28), 2); } } }
    d = CreateFileA("hgd3d9.nobleed", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); hg_texcache_set_bleed(0); }
    d = CreateFileA("hgd3d9.nolights", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_lights = 0; }
    { char ln[17] = "hgd3d9.lightr0", la[19] = "hgd3d9.lightamp0"; int q; void *hl;
      for (q = 1; q <= 9; q++) {
          ln[15] = (char)('0' + q); hl = CreateFileA(ln, 0x80000000, 3, 0, 3, 0x80, 0); if (hl != (void *)-1) { CloseHandle(hl); g_light_rscale = 0.25f * (float)q; }
          la[16] = (char)('0' + q); hl = CreateFileA(la, 0x80000000, 3, 0, 3, 0x80, 0); if (hl != (void *)-1) { CloseHandle(hl); g_light_amp = 0.25f * (float)q; }
      } }
    d = CreateFileA("hgd3d9.glowtrue", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_glowlift = 0; }
    d = CreateFileA("hgd3d9.nosort", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_nosort = 1; }
    if (g_hidefar) g_odepth = 4;
    g_glownowrite = g_glowlift;               /* lifted glows (see glowtrue) only test depth: written, their raised depth would hide the blast sprite and debris. With the true depth (hgd3d9.glowtrue) they write it like every other draw: one drawn before the ground must hide it where it is nearer (hardware stream, frame 1106) */
    d = CreateFileA("hgd3d9.glownowrite", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_glownowrite = 1; }
    { char nm[16] = "hgd3d9.bias0"; uint32_t k;
      for (k = 1; k <= 6; k++) { nm[13] = (char)('0' + k); d = CreateFileA(nm, 0x80000000, 3, 0, 3, 0x80, 0); if (d != (void *)-1) { CloseHandle(d); g_mipmode = 1 + (int)k; } } }
    g_forcemips = 1; g_state7 = 1;           /* mipmaps on whatever SetState 7 says: the base level alone sparkles where native is smooth */
    d = CreateFileA("hgd3d9.nomips", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_forcemips = 0; g_state7 = 1; }
    d = CreateFileA("hgd3d9.wquant", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_wquant = 1; }
    d = CreateFileA("hgd3d9.timelapse", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_timelapse = 1; }
    d = CreateFileA("hgd3d9.ab", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { CloseHandle(d); g_ab = 1; }
    put("---- FirstDevice, backend "); put(g_be->name); put(g_dump ? ", frame dumps on" : ""); put(g_cap ? ", CAPTURING to hgd3d9.cap" : ""); put(g_tee ? ", TEE with the real 3Dfx plugin" : ""); put(g_wquant ? ", W-buffer depth quantisation" : ""); put(g_ab ? ", A/B: ours alternates ON/OFF every 240 frames" : ""); put("\r\n");
    if (g_tee) {
        int r = g_real.first(info);        /* the real plugin first: it opens Glide, our device attaches to the game window */
        put("tee: real FirstDevice returned "); putdec((uint32_t)r); put("\r\n");
        if (r) { g_tee = 0; }
    }
    p.window = GetActiveWindow();            /* the game's own window exists before this call */
    g_game_wnd = p.window;
    d = CreateFileA("hgd3d9.window", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) {
        CloseHandle(d);
        g_own_wnd = make_own_window();
        if (g_own_wnd) { p.window = g_own_wnd; put("drawing into our own window\r\n"); } else put("could not create our own window; using the game's\r\n");
    }
    p.out_w = p.out_h = 0;
    {   /* hgd3d9.res holds "WIDTHxHEIGHT" (written by res.sh); it wins over the hgd3d9.resNNNN marker files below */
        void *f = CreateFileA("hgd3d9.res", 0x80000000, 3, 0, 3, 0x80, 0);
        if (f != (void *)-1) {
            char b[40]; uint32_t n = 0, i = 0, w = 0, h = 0;
            if (!ReadFile(f, b, 39, &n, 0)) n = 0;
            CloseHandle(f); b[n < 39 ? n : 39] = 0;
            while (i < n && b[i] >= '0' && b[i] <= '9' && w < 100000) w = w * 10 + (uint32_t)(b[i++] - '0');
            if (i < n && (b[i] == 'x' || b[i] == 'X')) { i++; while (i < n && b[i] >= '0' && b[i] <= '9' && h < 100000) h = h * 10 + (uint32_t)(b[i++] - '0'); }
            if (w >= 320 && w <= 7680 && h >= 240 && h <= 4320) { p.out_w = w; p.out_h = h; put("resolution from hgd3d9.res: "); putdec(w); put("x"); putdec(h); put("\r\n"); }
            else put("hgd3d9.res ignored (want WIDTHxHEIGHT)\r\n");
        }
    }
    { static const char *rn[8] = { "hgd3d9.res960", "hgd3d9.res1280", "hgd3d9.res1440", "hgd3d9.res1600", "hgd3d9.res1920", "hgd3d9.res2560", "hgd3d9.res1920x1080", "hgd3d9.res2880" };
      static const uint32_t rw[8] = { 960, 1280, 1440, 1600, 1920, 2560, 1920, 2880 }, rh[8] = { 720, 960, 1080, 1200, 1440, 1920, 1080, 2160 }; uint32_t k;   /* 4:3 sizes; the last one is wider, to check the side bars */
      if (!p.out_w) for (k = 0; k < 8; k++) { d = CreateFileA(rn[k], 0x80000000, 3, 0, 3, 0x80, 0); if (d != (void *)-1) { CloseHandle(d); p.out_w = rw[k]; p.out_h = rh[k]; } } }
    p.samples = 1;
    p.vsync = 0;                             /* the game's limiter paces frames; waiting for vblank as well can drop a frame to half rate */
    d = CreateFileA("hgd3d9.vsync", 0x80000000, 3, 0, 3, 0x80, 0);
    if (d != (void *)-1) { p.vsync = 1; CloseHandle(d); }
    if (g_be->init(&p)) { put("backend init failed\r\n"); return 1; }
    g_ready = 1;
    if (g_tee) { survey_windows("after both devices"); arrange_windows(); }
    g_be->set_mipmaps(g_forcemips ? g_mipmode : g_state7 != 0);
    g_be->set_fog_color(info[5] & 0x00ffffffu);              /* DeviceInfo+0x14, the colour the 3Dfx plugin gives grFogColorValue */
    QueryPerformanceFrequency(&g_qpf);
    QueryPerformanceCounter(&g_last_qpc);
    put("FirstDevice ok, window "); putdec((uint32_t)(uintptr_t)p.window); put("\r\n");
    return 0;
}
EXPORT void LastDevice(void)
{
    if (g_cap) { hg_cap_close(); g_cap = 0; }
    if (g_ready) { hg_texcache_clear(g_be); g_be->shutdown(); }
    g_ready = 0;
    if (g_own_wnd) { DestroyWindow(g_own_wnd); g_own_wnd = 0; }
    if (g_tee) { g_real.last(); g_tee = 0; }
}

EXPORT int RenderRefresh(void) { return g_tee ? g_real.renderrefresh() : 0; }

/* ---- blended sprites are drawn far to near ---------------------------------------------------------------------------------
 * The engine sorts the sprites of one particle effect, not those of different effects, so with real depth (hgfix partdepth) a nearer effect drawn first would block
 * a farther one. Runs of consecutive blended textured draws are held and drawn sorted by depth (farthest first); any other draw, a depth clear or the end of the
 * frame ends the run. The sort is stable, so sprites without depth (all w = 1) keep the engine's order. hgd3d9.nosort turns this off. */
#define SPR_MAX   4096
#define SPR_VERTS 12
typedef struct SprDraw { HgVertex v[SPR_VERTS]; uint32_t n; HgTex *tex; HgDrawState st; float key; } SprDraw;
static SprDraw  g_spr[SPR_MAX];
static uint16_t g_spr_ord[SPR_MAX], g_spr_tmp[SPR_MAX];
static uint32_t g_spr_n;

static void flush_sprites(void)
{
    uint32_t n = g_spr_n, w, i, lo, mid, hi, a, b, k;
    if (!n) return;
    g_spr_n = 0;
    for (i = 0; i < n; i++) g_spr_ord[i] = (uint16_t)i;
    for (w = 1; w < n; w *= 2) {                                 /* bottom-up merge sort of the indices by key, stable */
        for (lo = 0; lo < n; lo += 2 * w) {
            mid = lo + w < n ? lo + w : n; hi = lo + 2 * w < n ? lo + 2 * w : n;
            a = lo; b = mid; k = lo;
            while (a < mid && b < hi) g_spr_tmp[k++] = g_spr[g_spr_ord[b]].key < g_spr[g_spr_ord[a]].key ? g_spr_ord[b++] : g_spr_ord[a++];
            while (a < mid) g_spr_tmp[k++] = g_spr_ord[a++];
            while (b < hi) g_spr_tmp[k++] = g_spr_ord[b++];
        }
        for (i = 0; i < n; i++) g_spr_ord[i] = g_spr_tmp[i];
    }
    for (i = 0; i < n; i++) { SprDraw *s = &g_spr[g_spr_ord[i]]; g_be->draw_fan(s->v, s->n, s->tex, &s->st); }
}

/* ---- point lights ----------------------------------------------------------------------------------------------------------
 * The game draws an explosion's light as four flat quads in the horizontal plane at the blast's height (FUN_100977a8 in the 1.2 decompilation): the
 * centre vertex has alpha 64, the others 0. On a slope that plane meets the ground along a line, so only a strip lights up. The fans of one light are
 * collected here (they share the centre vertex), turned into a camera-space point and radius, and drawn by the backend as a sphere of light (HgLight).
 * If the backend cannot, the fans are drawn as they came. hgd3d9.nolights draws the fans always. The projection (centre 320, 240, focal length 320
 * pixels, a 90 degree field) was found by fitting the glow geometry: the angles of the quads are right only at f = 320. */
#define LT_POLYS 8
static struct {
    int active, overflow, derived; float pc[3], alpha, col[3];
    float rmax2; uint32_t npoly; HgVertex poly[LT_POLYS][HG_CLIP_MAX]; uint32_t pn[LT_POLYS]; HgDrawState st;
} g_lt;
static uint32_t g_lstat[4];                              /* glow fans: lit by their centre vertex, by a reconstructed centre, joined to a light, drawn as the game does */

static float lt_sqrt(float v)
{
    union { float f; uint32_t u; } c; float x = v, h, y;
    if (!(x > 0.0f)) return 0.0f;
    h = x * 0.5f; c.f = x; c.u = 0x5f3759dfu - (c.u >> 1); y = c.f;
    y = y * (1.5f - h * y * y); y = y * (1.5f - h * y * y); y = y * (1.5f - h * y * y);
    return x * y;
}

static void lt_cam(float *p, const GameVertex *v)       /* camera-space position of a projected vertex */
{
    p[0] = (v->x - 320.0f) * v->w / 320.0f; p[1] = (v->y - 240.0f) * v->w / 320.0f; p[2] = v->w;
}
static float lt_d2(const float *a, const float *b) { float x = a[0] - b[0], y = a[1] - b[1], z = a[2] - b[2]; return x * x + y * y + z * z; }
static int lt_free(const GameVertex *v) { return v->w > 162.0f && v->w < 1.0e7f; }    /* not on the near plane (w = 161: where the engine cut the quad) */

static void flush_light(void)
{
    HgLight l; float r, zc, sx, sy, rp;
    if (!g_lt.active) return;
    g_lt.active = 0;
    r = lt_sqrt(g_lt.rmax2) * g_light_rscale;
    if (g_lights_ok && !g_lt.overflow && g_be->draw_light && r > 1.0f) {
        l.pos[0] = g_lt.pc[0]; l.pos[1] = g_lt.pc[1]; l.pos[2] = g_lt.pc[2];
        l.inv_radius = 1.0f / r; l.amp = g_lt.alpha * g_light_amp;
        l.col[0] = g_lt.col[0]; l.col[1] = g_lt.col[1]; l.col[2] = g_lt.col[2];
        zc = g_lt.pc[2] - r;                                 /* the sphere's reach on screen: f * r / (z - r), the whole view if the camera is inside it */
        if (zc > r * 0.05f && zc > 1.0f) {
            sx = 320.0f + 320.0f * g_lt.pc[0] / g_lt.pc[2]; sy = 240.0f + 320.0f * g_lt.pc[1] / g_lt.pc[2]; rp = 320.0f * r / zc; l.x0 = sx - rp; l.x1 = sx + rp; l.y0 = sy - rp; l.y1 = sy + rp; }
        else { l.x0 = 0.0f; l.y0 = 0.0f; l.x1 = 640.0f; l.y1 = 480.0f; }
        if (g_be->draw_light(&l) == 0) return;
        g_lights_ok = 0;                                     /* the backend cannot: the game's own glow from now on */
    }
    if (!g_lt.overflow) { uint32_t i; for (i = 0; i < g_lt.npoly; i++) g_be->draw_fan(g_lt.poly[i], g_lt.pn[i], (HgTex *)0, &g_lt.st); }
}

/* The light's centre. With the centre vertex in view it is that vertex. When the centre lies behind the near plane the quads lose it, but a kite
 * (centre, corner K1, tip T, corner K2) with three consecutive unclipped vertices K1, T, K2 gives it back: centre = 3 * mid(K1, K2) - 2 T. */
static int lt_centre(const GameVertex *v, uint32_t count, uint32_t *ci, float *pc, float *alpha, const HgVertex *out)
{
    uint32_t i, c = count; float best = 0.0f;
    for (i = 0; i < count; i++) { float a = (float)(out[i].color >> 24); if (a > best) { best = a; c = i; } }
    if (c < count && v[c].w > 1.0f && v[c].w < 1.0e7f) { lt_cam(pc, &v[c]); *alpha = best / 255.0f; *ci = c; return 1; }
    for (i = 0; i + 2 < count; i++) {
        float a[3], b[3], d[3], ab, bc, ac;
        if (!lt_free(&v[i]) || !lt_free(&v[i + 1]) || !lt_free(&v[i + 2])) continue;
        lt_cam(a, &v[i]); lt_cam(b, &v[i + 1]); lt_cam(d, &v[i + 2]);
        ab = lt_sqrt(lt_d2(a, b)); bc = lt_sqrt(lt_d2(b, d)); ac = lt_sqrt(lt_d2(a, d));
        if (ab < 1.0f || bc < 1.0f) continue;
        if (ab > bc * 1.04f || bc > ab * 1.04f) continue;                          /* K1 T and T K2 are both sqrt(5) / 2 r */
        if (ac < ab * 1.70f || ac > ab * 1.88f) continue;                          /* K1 K2 = 2 r = 1.789 K1 T */
        { uint32_t k; for (k = 0; k < 3; k++) pc[k] = 1.5f * (a[k] + d[k]) - 2.0f * b[k]; }
        *alpha = 64.0f / 255.0f; *ci = count; return 2;
    }
    return 0;
}

/* One glow fan: returns 1 if it was taken (drawn later as a light), 0 if the caller should draw it. */
static int light_take(const GameVertex *verts, const HgVertex *clipped, uint32_t n, const HgVertex *out, uint32_t count, const HgDrawState *st)
{
    uint32_t i, c; float pc[3], alpha; int how;
    if (!g_lights || !g_lights_ok || !g_be->draw_light) return 0;
    how = lt_centre(verts, count, &c, pc, &alpha, out);
    if (!how) {
        if (!g_lt.active || g_lt.overflow) { g_lstat[3]++; return 0; }                                              /* a quad of a light whose centre is not in this fan: it joins the light under way if it lies within its reach */
        if (!g_lt.active || g_lt.overflow) return 0;
        for (i = 0; i < count; i++) if (lt_free(&verts[i])) { float p[3]; lt_cam(p, &verts[i]); if (lt_d2(p, g_lt.pc) > g_lt.rmax2 * 1.2f) { g_lstat[3]++; return 0; } }
        g_lstat[2]++; goto add_poly;
    }
    g_lstat[how == 1 ? 0 : 1]++;
    if (g_lt.active && lt_d2(pc, g_lt.pc) > 0.0004f * (pc[2] * pc[2])) flush_light();
    if (!g_lt.active) {
        g_lt.active = 1; g_lt.overflow = 0; g_lt.npoly = 0; g_lt.rmax2 = 0.0f; g_lt.st = *st; g_lt.derived = how == 2;
        g_lt.pc[0] = pc[0]; g_lt.pc[1] = pc[1]; g_lt.pc[2] = pc[2]; g_lt.alpha = alpha;
        g_lt.col[0] = (float)verts[0].r / 255.0f; g_lt.col[1] = (float)verts[0].g / 255.0f; g_lt.col[2] = (float)verts[0].b / 255.0f;
    }
    for (i = 0; i < count; i++) {
        float p[3], d2;
        if ((how == 1 && i == c) || !lt_free(&verts[i])) continue;
        lt_cam(p, &verts[i]); d2 = lt_d2(p, g_lt.pc); if (d2 > g_lt.rmax2) g_lt.rmax2 = d2;
    }
add_poly:
    if (g_lt.npoly < LT_POLYS && n <= HG_CLIP_MAX) { uint32_t q; for (q = 0; q < n; q++) g_lt.poly[g_lt.npoly][q] = clipped[q]; g_lt.pn[g_lt.npoly++] = n; }
    else g_lt.overflow = 1;
    return 1;
}

static int do_render_impl(uint32_t prim, const GameVertex *verts, uint32_t count, uint32_t arg);
static int do_render(uint32_t prim, const GameVertex *verts, uint32_t count, uint32_t arg, int noclip, uint32_t caller)
{
    int64_t t0, t1; int r;
    if (g_cap) hg_cap_caller(caller);
    if (prim >= 21 || g_info[prim].kind == K_NONE) g_odd_prim++;       /* primitives we do not draw: the capture records them anyway */
    if (g_cap && (prim >= 21 || g_info[prim].kind == K_NONE)) hg_cap_render(prim, verts, count, (const uint32_t *)0, 0, noclip);
    if (g_cap && prim < 21 && g_info[prim].kind != K_NONE) {
        const uint32_t *block = (const uint32_t *)(uintptr_t)arg;
        const PrimInfo *ci = &g_info[prim];
        if (ci->kind == K_TEX) hg_cap_render(prim, verts, count, hg_readable(block, 64) ? block : (const uint32_t *)0, 0, noclip);
        else hg_cap_render(prim, verts, count, (const uint32_t *)0, (ci->kind == K_FILL_CONST || ci->kind == K_POINTS) && hg_readable(block, 8) ? block[1] : 0, noclip);
    }
    QueryPerformanceCounter(&t0);
    if (!g_first_render) g_first_render = t0;
    r = do_render_impl(prim, verts, count, arg);
    QueryPerformanceCounter(&t1);
    g_t_render += t1 - t0;
    g_last_render_end = t1;
    return r;
}

static int do_render_impl(uint32_t prim, const GameVertex *verts, uint32_t count, uint32_t arg)
{
    HgVertex out[MAX_POLY];
    HgDrawState st;
    ConvertCtx cc;
    const PrimInfo *pi;
    HgTex *tex = (HgTex *)0;
    uint32_t i, constant = 0;
    g_renders++;
    if (prim < 32) { g_prim[prim]++; g_fprim[prim]++; }
    pi = prim < 21 ? &g_info[prim] : &g_info[5];
    if (pi->kind == K_NONE) { g_noop++; return 0; }
    if (g_spr_n && !(pi->kind == K_TEX && pi->blend)) flush_sprites();
    if (g_lt.active && prim != 17) flush_light();
    if (!g_on) return 0;                     /* A/B test: our drawing is off in this window */
    if (prim < 21 && (g_skip >> prim & 1)) return 0;
    if (g_sky2skip && prim == 2 && !g_sky_done) return 0;
    if (g_dump && g_sliver_logged < 80 && g_frame >= 100 && verts && count >= 3 && count <= MAX_POLY && hg_readable(verts, count * 36)) {
        float x0 = verts[0].x, x1 = x0, y0 = verts[0].y, y1 = y0; uint32_t k;
        for (k = 1; k < count; k++) {
            if (verts[k].x < x0) x0 = verts[k].x; if (verts[k].x > x1) x1 = verts[k].x;
            if (verts[k].y < y0) y0 = verts[k].y; if (verts[k].y > y1) y1 = verts[k].y;
        }
        if (y1 - y0 < 1.6f && x1 - x0 > 20.0f && y1 > -100.0f && y0 < 580.0f) {
            g_sliver_logged++;
            put("sliver prim "); putdec(prim); put(" count "); putdec(count); put(" frame "); putdec(g_frame);
            put(" x "); putdec((uint32_t)(int32_t)x0); put(".."); putdec((uint32_t)(int32_t)x1);
            put(" y "); putdec((uint32_t)(int32_t)y0); put(".."); putdec((uint32_t)(int32_t)y1);
            for (k = 0; k < count && k < 3; k++) {
                const uint32_t *w = (const uint32_t *)(const void *)&verts[k];
                put(" [w="); putdec((uint32_t)verts[k].w); put(" rgba="); hg_log_hex(w[5]); put(" fog="); hg_log_hex(w[6]); put("]");
            }
            put("\r\n");
        }
    }
    if (g_dump && g_ll_start && g_frame - g_ll_start < 150 && (prim == 15 || prim == 18 || prim == 19 || prim == 1 || prim == 2) && g_ll_vlog[prim & 31] < 5 && verts && count >= 2 && count <= MAX_POLY && hg_readable(verts, count * 36)) {
        uint32_t k;
        g_ll_vlog[prim & 31]++;
        put("low-light poly prim "); putdec(prim); put(" count "); putdec(count); put(" frame "); putdec(g_frame); put(":");
        for (k = 0; k < count && k < 4; k++) {
            const uint32_t *w = (const uint32_t *)(const void *)&verts[k];
            put(" [x="); putdec((uint32_t)(int32_t)verts[k].x); put(" y="); putdec((uint32_t)(int32_t)verts[k].y); put(" w="); putdec((uint32_t)verts[k].w); put(" oow_x1e9="); putdec((uint32_t)(verts[k].oow * 1e9f)); put(" light="); putdec(verts[k].light);
            put(" rgba="); hg_log_hex(w[5]); put(" fogword="); hg_log_hex(w[6]); put("]");
        }
        put("\r\n");
    }
    if (g_dump && g_frame >= 300 && (prim == 17 || prim == 8 || prim == 12 || prim == 13 || prim == 7) && g_vlog[prim & 31] < 6 && verts && count >= 3 && count <= MAX_POLY && hg_readable(verts, count * 36)) {
        uint32_t k;
        g_vlog[prim & 31]++;
        put("poly prim "); putdec(prim); put(" count "); putdec(count); put(" frame "); putdec(g_frame); put(":");
        for (k = 0; k < count && k < 4; k++) {
            const uint32_t *w = (const uint32_t *)(const void *)&verts[k];
            put(" ["); put("x="); putdec((uint32_t)(int32_t)verts[k].x); put(" y="); putdec((uint32_t)(int32_t)verts[k].y); put(" w="); putdec((uint32_t)verts[k].w); put(" oow_x1e9="); putdec((uint32_t)(verts[k].oow * 1e9f)); put(" light="); putdec(verts[k].light);
            put(" rgba="); hg_log_hex(w[5]); put(" fogword="); hg_log_hex(w[6]); put("]");
        }
        put("\r\n");
    }
    if (!g_ready || !verts || count < 1 || count > MAX_POLY) { g_skipped++; return 1; }
    if ((pi->kind == K_FILL_CONST || pi->kind == K_POINTS)) {
        const uint32_t *block = (const uint32_t *)(uintptr_t)arg;
        if (!hg_readable(block, 8)) { g_skipped++; return 1; }
        constant = 0xff000000u | (block[1] & 0x00ffffffu);       /* grConstantColorValue(*(arg + 4)) */
    }
    cc.blend = pi->blend;
    cc.far_w = g_far_w;
    cc.textured = pi->kind == K_TEX;
    cc.lit = pi->lit;
    cc.alpha_from_fog = pi->kind == K_FILL || pi->kind == K_FILL_CONST;   /* prims 14 to 17 */
    if (g_p17modes && (prim == 16 || prim == 17) && (g_p17mode == 1 || g_p17mode == 2 || g_p17mode == 3)) { cc.alpha_from_fog = 0; cc.blend = 1; }
    cc.wquant = g_wquant;
    cc.rhw_depth = g_rhw_depth;
    cc.u_scale = cc.v_scale = 0.0f;          /* D3D textures have the real width and height, so no aspect scale */
    if (cc.textured) {
        const uint32_t *block = (const uint32_t *)(uintptr_t)arg;
        if (!hg_readable(block, 64)) { g_notex++; return 1; }
        tex = hg_texcache_get(g_be, block, g_frame, pi->keyed);
        if (!tex) { g_notex++; return 1; }
    }
    for (i = 0; i < count; i++) {
        hg_convert_vertex(&out[i], &verts[i], &cc);
        if (constant) out[i].color = constant;
        if (g_p17modes && (prim == 16 || prim == 17) && (g_p17mode == 2 || g_p17mode == 4)) {   /* red and blue swapped */
            uint32_t c = out[i].color;
            out[i].color = (c & 0xff00ff00u) | ((c >> 16) & 0xffu) | ((c & 0xffu) << 16);
        }
    }
    if (g_fillw && pi->kind == K_FILL && !pi->blend) {
        /* The 1/w word of an opaque fill can be stale (not the 1/w of its own w). That is harmless on a mech's small fills, but a huge ground fill (vertices thousands of pixels
         * off screen) then has the wrong depth across its middle and lets distant terrain lines peek through. For polygons that large, derive 1/w from the w word. */
        float ext = 0.0f;
        for (i = 0; i < count; i++) { float ax = verts[i].x < 0 ? -verts[i].x : verts[i].x, ay = verts[i].y < 0 ? -verts[i].y : verts[i].y; if (ax > ext) ext = ax; if (ay > ext) ext = ay; }
        float wsum = 0.0f; uint32_t nw = 0;
        for (i = 0; i < count; i++) if (verts[i].w > 1.0f && verts[i].w < 1.0e7f) { wsum += verts[i].w; nw++; }
        if ((ext > g_fillw_ext || (nw && wsum / (float)nw > g_fillw_far)) && nw == count) for (i = 0; i < count; i++) if (verts[i].w > 1.0f && verts[i].w < 1.0e7f) out[i].rhw = 1.0f / verts[i].w;
    }
    if (!g_nodrawbias && !pi->blend && (pi->kind == K_TEX || pi->kind == K_FILL || pi->kind == K_FILL_CONST)) {      /* opaque draws only (shadows and glows are blended: leave them); later draws a hair nearer: ties go to the later one */
        float sc = 1.0f + (float)g_draw_idx * 5e-7f;
        for (i = 0; i < count; i++) out[i].rhw *= sc;
    }
    g_draw_idx++;
    if (g_glowlift && (prim == 16 || prim == 17)) {      /* the glow is a horizontal disc around the blast: on a slope the hill behind the blast lies in front of the disc's far rim and hid it. No part of it is placed farther than the blast itself */
        float c = 0.0f; uint32_t best = 0;
        for (i = 0; i < count; i++) if ((out[i].color >> 24) >= best) { best = out[i].color >> 24; c = out[i].rhw; }
        for (i = 0; i < count; i++) if (out[i].rhw < c) out[i].rhw = c;
    }
    if (g_glow_bias > 0.0f && (prim == 16 || prim == 17)) for (i = 0; i < count; i++) out[i].rhw *= 1.0f + g_glow_bias;
    st.pad = 0;
    st.blend = pi->blend ? HG_BLEND_ALPHA : HG_BLEND_NONE;
    if (pi->kind == K_TEX && pi->blend && !g_nosprite2) { st.depth = 2; st.pad = 2; }
    if (pi->kind == K_TEX && pi->blend && g_spr_opacity < 1.0f) for (i = 0; i < count; i++) { uint32_t al = (uint32_t)((float)(out[i].color >> 24) * g_spr_opacity); out[i].color = (out[i].color & 0x00ffffffu) | (al << 24); }   /* blended sprites: test depth, write only their solid texels (backend, second pass) */
    /* Fog follows the plugin: its textured routine turns fog off around blended draws and its outline routine around outlines, but its fill
     * routine (prims 14 to 17) never touches it, so blended fills are fogged first and then blended. */
    st.fog = (uint8_t)(g_fog && ((pi->kind == K_TEX && !pi->blend) || pi->kind == K_FILL || pi->kind == K_FILL_CONST));
    if (g_p17modes && (prim == 16 || prim == 17) && (g_p17mode == 1 || g_p17mode == 2)) st.fog = 0;
    st.depth = 1;
    if (g_glownowrite && (prim == 16 || prim == 17)) st.depth = 2;
    if (pi->kind == K_OUTLINE) {
        st.depth = (uint8_t)(g_odepth == 0 ? 0 : (g_odepth == 1 ? 2 : 1));
        if (g_odepth == 4) { st.depth = 2; st.pad = 3; }
        if (g_hidemodels && !(out[0].color == 0xffffffffu)) {          /* (colour test below) */ }
        if (g_hidemodels) {
            const GameVertex *gv = &verts[0];
            if (!(gv->r == 0x58 && gv->g == 0 && gv->b == 0)) { st.depth = 2; st.pad = 3; }   /* models, rocks, damage: occluded by terrain fills */
        }               /* hidefar: test only, 25% bias in the backend */
        if (g_odepth == 3) { st.depth = 2; st.pad = 1; }       /* test only, biased by 1000x in 1/w: lose only to the w = 1 screen-space sprites */
    }
    if (g_fillnowrite && pi->kind == K_FILL && !pi->blend) st.depth = 2;
    if (g_hidemodels && pi->kind == K_FILL && !pi->blend) {            /* fills write true depth, except the background fills (a vertex with a 1/w of 0 or above 1, or w at infinity: garbage depth) */
        int bg = 0;
        for (i = 0; i < count; i++) if (!(verts[i].oow > 0.0f && verts[i].oow <= 1.0f) || verts[i].w >= 1.0e7f) bg = 1;
        st.depth = bg ? 0 : 1;
    }
    if (g_sky_painter && !g_sky_done) st.depth = 0;
    switch (pi->kind) {
    case K_OUTLINE: {
        HgVertex clipped[HG_CLIP_MAX];
        uint32_t n = count >= 3 ? hg_clip_rect(clipped, out, count, 0.0f, 0.0f, 639.0f, 479.0f) : 0;
        if (count < 3) g_be->draw_outline(out, count, &st);
        else if (n >= 3) g_be->draw_outline(clipped, n, &st);
        break; }
    case K_POINTS:  g_be->draw_points(out, count, &st); break;
    default:
        if (count >= 3) {
            HgVertex clipped[HG_CLIP_MAX];
            uint32_t n = g_noclip ? count : hg_clip_fan(clipped, out, count);
            if (g_noclip) { uint32_t q; for (q = 0; q < count; q++) clipped[q] = out[q]; }       /* the engine's ground polygons reach +-20000 pixels */
            if (n >= 3) {
                if (pi->kind == K_TEX && pi->blend && !g_nosort && n <= SPR_VERTS && g_spr_n < SPR_MAX) {
                    SprDraw *s = &g_spr[g_spr_n++]; uint32_t q; float sum = 0.0f;
                    for (q = 0; q < n; q++) { s->v[q] = clipped[q]; sum += clipped[q].rhw; }
                    s->n = n; s->tex = tex; s->st = st; s->key = sum / (float)n;
                } else if (prim == 17 && light_take(verts, clipped, n, out, count, &st)) {
                    /* drawn as a light when the next other draw arrives */
                } else {
                    flush_sprites(); flush_light();
                    g_be->draw_fan(clipped, n, tex, &st);
                }
            }
        }
        break;
    }
    return 0;
}
EXPORT int Render(uint32_t prim, uint32_t *ctx, GameVertex *v, uint32_t count, uint32_t arg)
{
    int r = do_render(prim, v, count, arg, 0, (uint32_t)(uintptr_t)__builtin_return_address(0));
    if (g_tee) { int64_t a, b; QueryPerformanceCounter(&a); r = g_real.render(prim, ctx, v, count, arg); QueryPerformanceCounter(&b); g_n_render += b - a; }
    return r;
}
EXPORT int RenderNoClip(uint32_t prim, uint32_t *ctx, GameVertex *v, uint32_t count, uint32_t arg)
{
    int r = do_render(prim, v, count, arg, 1, (uint32_t)(uintptr_t)__builtin_return_address(0));
    if (g_tee) { int64_t a, b; QueryPerformanceCounter(&a); r = g_real.rendernoclip(prim, ctx, v, count, arg); QueryPerformanceCounter(&b); g_n_render += b - a; }
    return r;
}

/* SetState as the 1.2 3Dfx plugin implements it (renderer-interface.md section 5). */
static int set_state_impl(uint32_t state, uint32_t value);
EXPORT int SetState(uint32_t state, uint32_t value)
{
    int64_t a, b; int r;
    if (g_cap) hg_cap_setstate(state, value);
    QueryPerformanceCounter(&a);
    r = set_state_impl(state, value);
    QueryPerformanceCounter(&b);
    g_t_setstate += b - a;
    if (g_tee) { QueryPerformanceCounter(&a); r = g_real.setstate(state, value); QueryPerformanceCounter(&b); g_n_setstate += b - a; }
    return r;
}
static int set_state_impl(uint32_t state, uint32_t value)
{
    switch (state) {
    case 1:   if (g_fog != (value == 0x200000)) { put("fog "); put(value == 0x200000 ? "on" : "off"); put(" at frame "); putdec(g_frame); put("\r\n"); }
              if (value != 0x200000 && g_fog) { g_ll_start = g_frame ? g_frame : 1; { uint32_t k; for (k = 0; k < 32; k++) g_ll_vlog[k] = 0; } }
              if (value == 0x200000 && !g_fog) g_ll_start = 0;
              g_fog = (value == 0x200000); return 0;
    case 5:   if (g_state5 != value) { put("state 5 = "); putdec(value); put(" at frame "); putdec(g_frame); put("\r\n"); }
              g_state5 = value; return 0;
    case 7:   if (g_forcemips) return 0;
              if (g_state7 != value) { put("state 7 = "); putdec(value); put(" at frame "); putdec(g_frame); put("\r\n"); }
              g_state7 = value; if (g_ready) g_be->set_mipmaps(value != 0); return 0;
    case 0xc: g_sky_done = 1; flush_sprites(); flush_light(); if (g_ready && g_on) g_be->clear_depth(); return 0;
    case 0xd: return 0x400000;                /* total texture memory; the real plugin sums grTexMaxAddress. 4 MiB is a stand-in */
    case 0xe: if (g_depth_mode != value) { put("depth mode = "); putdec(value); put(" at frame "); putdec(g_frame); put("\r\n"); }
              g_depth_mode = value; return 0;
    default:  return 0;
    }
}
EXPORT int SetTexturePalette(uint32_t slot, uint32_t pal) { return g_tee ? g_real.palette(slot, pal) : 0; }

/* The 2D layer: the engine writes RGB565 into this buffer between LockDisplay and UnlockDisplay, then RefreshDisplay shows it. */
EXPORT uint32_t LockDisplay(uint32_t *stride_bytes)
{
    int64_t a, b;
    QueryPerformanceCounter(&a);
    g_real_buf = (uint8_t *)0;
    if (g_tee) {                                   /* lock the real plugin's buffer too; the engine writes into ours */
        uint32_t stride = 0;
        uint32_t p = g_real.lock(&stride);
        if (p) { g_real_buf = (uint8_t *)(uintptr_t)p; g_real_stride = stride; }
    }
    if (stride_bytes) *stride_bytes = PITCH;
    g_locked = 1; g_locks++;
    QueryPerformanceCounter(&b); g_t_lock += b - a;
    if (g_tee) g_n_lock += b - a;
    return (uint32_t)(uintptr_t)g_overlay;
}
EXPORT void UnlockDisplay(void)
{
    if (g_tee) {
        int64_t a, b;
        QueryPerformanceCounter(&a);
        if (g_real_buf && g_real_stride >= HG_GAME_W * 2) {   /* copy the pixels the engine wrote (non-zero), as our overlay does */
            uint32_t y, x;
            for (y = 0; y < HG_GAME_H; y++) {
                const uint16_t *src = (const uint16_t *)(const void *)(g_overlay + (size_t)y * PITCH);
                uint16_t *dst = (uint16_t *)(void *)(g_real_buf + (size_t)y * g_real_stride);
                for (x = 0; x < HG_GAME_W; x++) if (src[x]) dst[x] = src[x];
            }
        }
        g_real.unlock();
        g_real_buf = (uint8_t *)0;
        QueryPerformanceCounter(&b); g_n_lock += b - a;
    }
}

static void time_frame(void)
{
    int64_t now, dt; uint32_t cr, up, ms;
    QueryPerformanceCounter(&now);
    dt = now - g_last_qpc; g_last_qpc = now; g_sum_qpc += dt;
    if (g_qpf <= 0) return;
    ms = (uint32_t)((double)dt * 1000.0 / (double)g_qpf);
    hg_texcache_stats(&cr, &up);
    if (ms >= 60 && g_frame > 5) {            /* a slow frame: say what it did */
        g_slow++;
        put("slow frame "); putdec(g_frame); put(": "); putdec(ms); put(" ms, renders "); putdec(g_renders - g_prev_renders);
        put(", texture creates "); putdec(cr - g_prev_creates); put(", updates "); putdec(up - g_prev_updates);
        put(", live "); putdec(hg_texcache_count());
        put("; in plugin: render "); putdec((uint32_t)((double)g_t_render * 1000.0 / (double)g_qpf)); put(" ms, overlay ");
        putdec((uint32_t)((double)g_t_overlay * 1000.0 / (double)g_qpf)); put(" ms, present ");
        putdec((uint32_t)((double)g_t_present * 1000.0 / (double)g_qpf)); put(" ms, SetState ");
        putdec((uint32_t)((double)g_t_setstate * 1000.0 / (double)g_qpf)); put(" ms, whole RefreshDisplay ");
        putdec((uint32_t)((double)g_t_refresh * 1000.0 / (double)g_qpf));
        put(" ms; timeline: start-to-first-Render "); putdec((uint32_t)((double)g_seg_a * 1000.0 / (double)g_qpf));
        put(" ms, first-to-last-Render "); putdec((uint32_t)((double)g_seg_b * 1000.0 / (double)g_qpf));
        put(" ms, last-Render-to-Refresh "); putdec((uint32_t)((double)g_seg_c * 1000.0 / (double)g_qpf)); put(" ms");
        if (g_tee) { put("; NATIVE: render "); putdec((uint32_t)((double)g_n_render * 1000.0 / (double)g_qpf)); put(" ms, setstate ");
                     putdec((uint32_t)((double)g_n_setstate * 1000.0 / (double)g_qpf)); put(" ms, lock ");
                     putdec((uint32_t)((double)g_n_lock * 1000.0 / (double)g_qpf)); put(" ms, refresh ");
                     putdec((uint32_t)((double)g_n_refresh * 1000.0 / (double)g_qpf)); put(" ms"); }
        put("\r\n");
    }
    g_s_render += g_t_render; g_s_overlay += g_t_overlay; g_s_present += g_t_present;
    g_s_setstate += g_t_setstate; g_s_lock += g_t_lock; g_s_refresh += g_t_refresh;
    g_sn_render += g_n_render; g_sn_setstate += g_n_setstate; g_sn_lock += g_n_lock; g_sn_refresh += g_n_refresh;
    g_n_render = g_n_setstate = g_n_lock = g_n_refresh = 0;
    g_t_render = g_t_overlay = g_t_present = g_t_setstate = g_t_lock = g_t_refresh = 0;
    g_prev_renders = g_renders; g_prev_creates = cr; g_prev_updates = up;
}

EXPORT void RefreshDisplay(void)
{
    flush_sprites();
    int64_t rt0, rt1;
    QueryPerformanceCounter(&rt0);
    g_cap_ref = 0;
    if (g_cap) {                                   /* the 2D layer is still intact here; every 30th frame also gets reference pictures */
        g_cap_ref = g_ready && g_be->screenshot && g_frame % 30 == 15;
        if (g_ready && g_be->screenshot && !g_cap_ref && g_burst_refs < 250 && (g_frame - g_last_burst >= 5 || g_burst_refs == 0)) {
            /* an effect frame: more than the sky dome's keyed sprite, any other blended or unlit primitive, or one we do not know */
            uint32_t other = g_fprim[7] + g_fprim[9] + g_fprim[10] + g_fprim[11] + g_fprim[12] + g_fprim[13] + g_fprim[16] + g_fprim[19] + g_fprim[20];
            if (g_fprim[8] >= 4 || other || g_odd_prim) { g_cap_ref = 1; g_burst_refs++; g_last_burst = g_frame; }
        }
        hg_cap_frame(g_frame, (const uint16_t *)(const void *)g_overlay, g_locked, g_cap_ref);
    }
    if (g_first_render) {
        g_seg_a = g_first_render - g_frame_start; g_seg_b = g_last_render_end - g_first_render; g_seg_c = rt0 - g_last_render_end;
    } else { g_seg_a = rt0 - g_frame_start; g_seg_b = g_seg_c = 0; }
    if (g_ready) {
        if (g_locked && g_on) {
            HgOverlay o;
            o.pixels = (const uint16_t *)(const void *)g_overlay; o.pitch = PITCH; o.key = 0;
            { int64_t a, b; QueryPerformanceCounter(&a); g_be->draw_overlay(&o); QueryPerformanceCounter(&b); g_t_overlay += b - a; }
            memset(g_overlay, 0, sizeof g_overlay);
            g_locked = 0;
        } else if (g_locked) { memset(g_overlay, 0, sizeof g_overlay); g_locked = 0; }
        {   /* effect burst: blended Gouraud (16, 17), unlit textured (7 to 13) and points (20) in one frame */
            uint32_t fx = g_fprim[7] + g_fprim[8] + g_fprim[9] + g_fprim[10] + g_fprim[11] + g_fprim[12] + g_fprim[13] + g_fprim[16] + g_fprim[20], k;
            uint32_t f17 = g_fprim[17];            /* prim 17 runs at about 220 a frame all the time, so only a clearly higher count is a burst */
            if (g_dump && g_be->screenshot && g_on && (fx >= 6 || f17 >= 100) && g_fx_dumps < 24 && (g_fx_dumps == 0 || g_frame - g_fx_last >= 20)) {
                char name[24] = "hgfx_0000.bmp"; uint32_t f = g_frame;
                for (k = 0; k < 4; k++) { name[8 - k] = (char)('0' + f % 10); f /= 10; }
                put("effects burst, frame "); putdec(g_frame); put(":");
                for (k = 0; k < 32; k++) if (g_fprim[k]) { put(" p"); putdec(k); put("="); putdec(g_fprim[k]); }
                put(g_be->screenshot(name) ? " (screenshot failed)\r\n" : (" -> hgfx_" ));
                if (1) { put(name + 5); put("\r\n"); }
                g_nat_want = 1;
                g_fx_dumps++; g_fx_last = g_frame; g_vlog[17] = 0; g_vlog[8] = 0;   /* log the next polygons of prims 17 and 8 */
            }
        }
        if (g_timelapse && g_be->screenshot && g_on && (g_p17modes ? g_frame % 60 == 30 : g_frame % 90 == 45) && g_tl_count < 70) {
            char name[24] = "hgtl_0000.bmp"; uint32_t f = g_frame, k;
            for (k = 0; k < 4; k++) { name[8 - k] = (char)('0' + f % 10); f /= 10; }
            put("timelapse "); put(name); put(g_p17modes ? " p17mode=" : ""); if (g_p17modes) putdec(g_p17mode); put(":");
            for (k = 0; k < 32; k++) if (g_fprim[k]) { put(" p"); putdec(k); put("="); putdec(g_fprim[k]); }
            put(g_be->screenshot(name) ? " (screenshot failed)\r\n" : "\r\n");
            g_tl_count++; g_nat_want = 1;
        }
        if (g_dump && g_be->screenshot && g_on && g_ll_start && g_fx_dumps < 28 &&
            (g_frame - g_ll_start == 26 || g_frame - g_ll_start == 56 || g_frame - g_ll_start == 86 || g_frame - g_ll_start == 116 || g_frame - g_ll_start == 146)) {
            char name[24] = "hgll_0000.bmp"; uint32_t f = g_frame, k;
            for (k = 0; k < 4; k++) { name[8 - k] = (char)('0' + f % 10); f /= 10; }
            put("low-light capture, frame "); putdec(g_frame); put(" ("); putdec(g_frame - g_ll_start); put(" after fog off):");
            for (k = 0; k < 32; k++) if (g_fprim[k]) { put(" p"); putdec(k); put("="); putdec(g_fprim[k]); }
            put(g_be->screenshot(name) ? " (screenshot failed)\r\n" : " -> "); put(name); put("\r\n");
            g_fx_dumps++; g_nat_want = 1;
        }
        if (g_shot_name[0]) { if (g_be->screenshot(g_shot_name)) put("requested screenshot failed\r\n"); g_shot_name[0] = 0; }
        if (g_cap_ref && g_on) {
            char name[24] = "hgcap_0000.bmp"; uint32_t f = g_frame, k;
            for (k = 0; k < 4; k++) { name[9 - k] = (char)('0' + f % 10); f /= 10; }
            if (g_be->screenshot(name)) put("capture reference failed\r\n");
            g_nat_want = 1;
        }
        if (g_dump && g_be->screenshot && (g_frame == 30 || g_frame == 300 || g_frame == 900 || g_frame == 1800 || g_frame == 3000)) {
            char name[24] = "hgframe_0000.bmp"; uint32_t f = g_frame, k;
            for (k = 0; k < 4; k++) { name[11 - k] = (char)('0' + f % 10); f /= 10; }
            put("screenshot "); put(name); put(g_be->screenshot(name) ? " failed\r\n" : " ok\r\n");
            g_nat_want = 1;
        }
        if (g_on) { int64_t a, b; QueryPerformanceCounter(&a); g_be->present(); QueryPerformanceCounter(&b); g_t_present += b - a; }
        QueryPerformanceCounter(&rt1); g_t_refresh += rt1 - rt0;
        time_frame();
        g_s_a += g_seg_a; g_s_b += g_seg_b; g_s_c += g_seg_c;
    }
    if (g_tee && g_nat_want) { native_shot(); g_nat_want = 0; }
    if (g_tee) { int64_t a, b; QueryPerformanceCounter(&a); g_real.refresh(); QueryPerformanceCounter(&b); g_n_refresh += b - a; }
    { uint32_t k; for (k = 0; k < 32; k++) g_fprim[k] = 0; }
    g_odd_prim = 0;
    if (g_tee && (g_frame == 5 || g_frame == 90)) { if (g_frame == 5) survey_windows("frame 5"); arrange_windows(); }
    g_first_render = 0; g_last_render_end = 0; g_sky_done = 0; g_draw_idx = 0;
    QueryPerformanceCounter(&g_frame_start);
    g_frame++;
    if (g_frame % 240 == 0 && (g_lstat[0] | g_lstat[1] | g_lstat[2] | g_lstat[3])) { put("glow fans: centre "); putdec(g_lstat[0]); put(", rebuilt centre "); putdec(g_lstat[1]); put(", joined "); putdec(g_lstat[2]); put(", game glow "); putdec(g_lstat[3]); put("\r\n"); }
    if (g_ab && g_tee) g_on = (((g_frame / 240) & 1) == 0);   /* the next frame's setting */
    if (g_p17modes && !g_p17fixed) { uint32_t pm = (g_frame / 120) % 5; if (pm != g_p17mode) { g_p17mode = pm; put("p17 mode "); putdec(pm); put(" from frame "); putdec(g_frame); put("\r\n"); } }
    if (g_frame % 240 == 0) {
        if (g_ab && g_tee) put((((g_frame / 240 - 1) & 1) == 0) ? "  [window above: OURS ON]\r\n" : "  [window above: OURS OFF]\r\n");
        summary("periodic");
        if (g_qpf > 0) { put("  average frame "); putdec((uint32_t)((double)g_sum_qpc * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(" x0.1 ms, of which render "); putdec((uint32_t)((double)g_s_render * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", overlay "); putdec((uint32_t)((double)g_s_overlay * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", present "); putdec((uint32_t)((double)g_s_present * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", SetState "); putdec((uint32_t)((double)g_s_setstate * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", lock "); putdec((uint32_t)((double)g_s_lock * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", whole RefreshDisplay "); putdec((uint32_t)((double)g_s_refresh * 1000.0 / (double)g_qpf / 240.0 * 10.0)); put(" (x0.1 ms)\r\n");
          put("  timeline avg: start-to-first-Render "); putdec((uint32_t)((double)g_s_a * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", first-to-last-Render "); putdec((uint32_t)((double)g_s_b * 1000.0 / (double)g_qpf / 240.0 * 10.0));
          put(", last-Render-to-Refresh "); putdec((uint32_t)((double)g_s_c * 1000.0 / (double)g_qpf / 240.0 * 10.0)); put(" (x0.1 ms)\r\n"); }
        if (g_tee && g_qpf > 0) {
            put("  NATIVE path avg (x0.1 ms): render "); putdec((uint32_t)((double)g_sn_render * 1000.0 / (double)g_qpf / 240.0 * 10.0));
            put(", setstate "); putdec((uint32_t)((double)g_sn_setstate * 1000.0 / (double)g_qpf / 240.0 * 10.0));
            put(", lock+unlock "); putdec((uint32_t)((double)g_sn_lock * 1000.0 / (double)g_qpf / 240.0 * 10.0));
            put(", refresh "); putdec((uint32_t)((double)g_sn_refresh * 1000.0 / (double)g_qpf / 240.0 * 10.0)); put("\r\n");
        }
        g_sn_render = g_sn_setstate = g_sn_lock = g_sn_refresh = 0;
        g_s_a = g_s_b = g_s_c = 0;
        g_sum_qpc = 0; g_s_render = g_s_overlay = g_s_present = g_s_setstate = g_s_lock = g_s_refresh = 0;
    }
}

/* Not part of the game's API: an offline replay tool asks for our picture of the frame drawn so far (before RefreshDisplay). */
EXPORT int hgScreenshot(const char *path)   /* taken inside the next RefreshDisplay, after the 2D layer is drawn, as the live reference is */
{
    uint32_t i;
    if (!g_ready || !g_be->screenshot) return 1;
    for (i = 0; i < 31 && path[i]; i++) g_shot_name[i] = path[i];
    g_shot_name[i] = 0;
    return 0;
}

/* For the replay tool's draw-by-draw mode: a picture of what has been drawn so far, right now (before the 2D layer). */
EXPORT int hgScreenshotNow(const char *path) { flush_sprites(); flush_light(); return g_ready && g_be->screenshot ? g_be->screenshot(path) : 1; }

EXPORT int PreloadTexture(uint32_t tex) { return g_tee ? g_real.preload(tex) : 0; }    /* never called by the game; 0 = it fits */
EXPORT int UpdateTexture(uint32_t tex, uint32_t arg) { return g_tee ? g_real.update(tex, arg) : 0; }
EXPORT int RestoreDevice(void)
{
    int r = g_ready ? g_be->restore() : 0;      /* managed textures survive; see backend.h */
    if (g_tee) r = g_real.restore();
    return r;
}
EXPORT int LostDeviceDisplay(void) { return g_tee ? g_real.lost() : 0; }
