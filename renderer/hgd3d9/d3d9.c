/* d3d9.c - the Direct3D 9 backend. Draws the game's pre-projected polygons (D3DFVF_XYZRHW) into a windowed device
 * attached to the game's own window, scaled to the window with the 4:3 picture centred (pillarboxed).
 *
 * Every failing D3D9 call is logged with its HRESULT (the first 24), because the first thing that goes wrong on a new
 * machine is usually device creation: the game's window may still be held by DirectDraw. */
#include <stddef.h>
#include "backend.h"
#include "d3d9_min.h"
#include "shaders.h"
__declspec(dllimport) void *__stdcall CreateFileA(const char *, unsigned, unsigned, void *, unsigned, unsigned, void *);
__declspec(dllimport) int __stdcall CloseHandle(void *);

void *memset(void *, int, size_t);
void *memcpy(void *, const void *, size_t);
__declspec(dllimport) int __stdcall GetClientRect(HWND, RECT *);
__declspec(dllimport) int __stdcall AdjustWindowRect(RECT *, DWORD, int);
__declspec(dllimport) int __stdcall SetWindowPos(HWND, HWND, int, int, int, int, DWORD);
__declspec(dllimport) long __stdcall GetWindowLongA(HWND, int);

#define D3DERR_DEVICELOST     ((HRESULT)0x88760868)
#define D3DERR_DEVICENOTRESET ((HRESULT)0x88760869)
#define OVERLAY_W 1024                   /* power-of-two texture holding the 640x480 2D layer */
#define OVERLAY_H 512
#define MAX_POLY 32

static IDirect3D9             *g_d3d;
static IDirect3DDevice9       *g_dev;
static D3DPRESENT_PARAMETERS   g_pp;
static HWND                    g_wnd;
static IDirect3DTexture9      *g_overlay;
static float                   g_scale = 1.0f, g_ox, g_oy;
static float g_fx = 0.0f, g_fy = 0.0f;           /* extra offset for filled polygons in device pixels (hgd3d9.fillshiftN while experimenting) */
static int   g_dpass = 252;                       /* a blended sprite writes depth where its alpha reaches this (hgd3d9.dpassN sets N * 28): glows drawn after it light the ground only where the sprite is faint */
static int   g_aref = 16;                           /* alpha below this (0..255) is discarded for blended textured draws (the chroma key is a hard edge); hgd3d9.arefN sets N * 16 (default 16) */
static float g_oslope = 1.0f;                    /* pixels of slope added to the outline bias; hgd3d9.oslopeN overrides while experimenting */
static float g_obias = 1.25f;                     /* outline depth bias: 1/w times this (2% in w); hgd3d9.obiasN overrides while experimenting */
static int                     g_scene, g_lost, g_mips, g_vsync = 1;
static UINT                    g_bb_w, g_bb_h;              /* back buffer size; 0 = the client area */
static uint32_t                g_failures;
static uint32_t                s_frames, s_draws, s_binds, s_states, s_verts;   /* statistics, logged every 240 frames */

/* Frames in flight: an event query is issued after each present; polling them next frame says how many frames the driver has
 * accepted but not finished. A queue that grows is what makes the picture lag behind the controls. */
#define NQ 16
static IDirect3DQuery9        *g_q[NQ];
static uint8_t                 g_qp[NQ];
static uint32_t                g_qi, s_fl_sum, s_fl_max;
static int                     g_qok;

/* device state we change per draw, cached so that unchanged state costs nothing */
static int c_atest = -1;
static int c_textured = -1, c_blend = -1, c_depth = -1, c_point = -1, c_fog = -1;
static IDirect3DTexture9 *c_bound;

static void fail(const char *what, HRESULT hr)
{
    if (g_failures++ >= 24) return;
    hg_log("d3d9 "); hg_log(what); hg_log(" failed, hr "); hg_log_hex((uint32_t)hr); hg_log("\r\n");
}
#define TRY(call, what) do { HRESULT hr_ = (call); if (HG_D3D_FAILED(hr_)) fail(what, hr_); } while (0)
#define DEV (g_dev->lpVtbl)

static uint32_t g_fog_color = 0xff000000u;

/* ---- lighting pass: the opaque polygons of the frame are replayed into an R32F target holding each pixel's eye depth, and a light is then a
 * screen-space shader that rebuilds the camera-space position of each pixel from it (see HgLight in backend.h) ---- */
#define REC_VERTS 24576
#define REC_DRAWS 3072
static HgVertex                g_rec[REC_VERTS];
static uint16_t                g_rec_n[REC_DRAWS], g_rec_start[REC_DRAWS];
static uint32_t                g_nrec, g_nrecv, g_wvalid_n = 0xffffffffu;
static IDirect3DTexture9      *g_wtex;
static IDirect3DSurface9      *g_wsurf, *g_wdepth;
static IDirect3DPixelShader9  *g_psw, *g_psl;
static int                     g_lights_state;                 /* 0 not tried, 1 ready, -1 failed */

static void lights_release(void)
{
    if (g_psw) { g_psw->lpVtbl->Release(g_psw); g_psw = 0; }
    if (g_psl) { g_psl->lpVtbl->Release(g_psl); g_psl = 0; }
    if (g_wsurf) { g_wsurf->lpVtbl->Release(g_wsurf); g_wsurf = 0; }
    if (g_wdepth) { g_wdepth->lpVtbl->Release(g_wdepth); g_wdepth = 0; }
    if (g_wtex) { g_wtex->lpVtbl->Release(g_wtex); g_wtex = 0; }
    g_lights_state = 0; g_wvalid_n = 0xffffffffu;
}

static void queries_release(void)
{
    uint32_t i;
    for (i = 0; i < NQ; i++) { if (g_q[i]) { g_q[i]->lpVtbl->Release(g_q[i]); g_q[i] = 0; } g_qp[i] = 0; }
    g_qok = 0; g_qi = 0;
}

static void queries_create(void)
{
    uint32_t i;
    queries_release();
    for (i = 0; i < NQ; i++) {
        HRESULT hr = g_dev->lpVtbl->CreateQuery(g_dev, D3DQUERYTYPE_EVENT, &g_q[i]);
        if (HG_D3D_FAILED(hr)) { fail("CreateQuery", hr); queries_release(); return; }
    }
    g_qok = 1;
}

static void layout(void)
{
    float cw = 640.0f, ch = 480.0f, sx, sy;
    if (g_pp.BackBufferWidth && g_pp.BackBufferHeight) { cw = (float)g_pp.BackBufferWidth; ch = (float)g_pp.BackBufferHeight; }
    sx = cw / HG_GAME_W; sy = ch / HG_GAME_H;
    g_scale = sx < sy ? sx : sy;
    g_ox = (cw - HG_GAME_W * g_scale) * 0.5f;
    g_oy = (ch - HG_GAME_H * g_scale) * 0.5f;
}

/* Clip drawing to the 4:3 picture: polygons are clipped to the view with a margin (convert.c) and would otherwise show in the side bars. */
static void apply_viewport(void)
{
    D3DVIEWPORT9 vp; float w = HG_GAME_W * g_scale, h = HG_GAME_H * g_scale;
    vp.X = (DWORD)(g_ox + 0.5f); vp.Y = (DWORD)(g_oy + 0.5f); vp.Width = (DWORD)(w + 0.5f); vp.Height = (DWORD)(h + 0.5f); vp.MinZ = 0.0f; vp.MaxZ = 1.0f;
    if (vp.X + vp.Width > g_pp.BackBufferWidth) vp.Width = g_pp.BackBufferWidth - vp.X;
    if (vp.Y + vp.Height > g_pp.BackBufferHeight) vp.Height = g_pp.BackBufferHeight - vp.Y;
    DEV->SetViewport(g_dev, &vp);
}

static void set_filters(int point)
{
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_MINFILTER, point ? D3DTEXF_POINT : D3DTEXF_LINEAR);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_MAGFILTER, point ? D3DTEXF_POINT : D3DTEXF_LINEAR);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_MIPFILTER, (!point && g_mips) ? D3DTEXF_LINEAR : D3DTEXF_NONE);
    { union { float f; DWORD d; } b; b.f = g_mips > 1 ? -0.5f * (float)(g_mips - 1) : 0.0f; DEV->SetSamplerState(g_dev, 0, D3DSAMP_MIPMAPLODBIAS, b.d); }
    c_point = point;
}

static void apply_state(void)
{
    apply_viewport();
    DEV->SetFVF(g_dev, D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_SPECULAR | D3DFVF_TEX1);
    DEV->SetRenderState(g_dev, D3DRS_LIGHTING, 0);
    DEV->SetRenderState(g_dev, D3DRS_CULLMODE, D3DCULL_NONE);
    DEV->SetRenderState(g_dev, D3DRS_ZFUNC, D3DCMP_GREATEREQUAL);      /* reversed depth: 1/w, larger is nearer */
    DEV->SetRenderState(g_dev, D3DRS_FOGENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_FOGTABLEMODE, D3DFOG_NONE);     /* no table or vertex-computed fog: pre-transformed vertices carry */
    DEV->SetRenderState(g_dev, D3DRS_FOGVERTEXMODE, D3DFOG_NONE);    /* the fog factor in their specular alpha */
    DEV->SetRenderState(g_dev, D3DRS_FOGCOLOR, g_fog_color);
    DEV->SetRenderState(g_dev, D3DRS_SPECULARENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ALPHATESTENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ALPHAFUNC, D3DCMP_GREATER);
    DEV->SetRenderState(g_dev, D3DRS_ALPHAREF, 0);
    DEV->SetRenderState(g_dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    DEV->SetRenderState(g_dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    DEV->SetTextureStageState(g_dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    DEV->SetTextureStageState(g_dev, 0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    DEV->SetTextureStageState(g_dev, 0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    DEV->SetTextureStageState(g_dev, 0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    DEV->SetTextureStageState(g_dev, 1, D3DTSS_COLOROP, D3DTOP_DISABLE);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);   /* the 3Dfx plugin uses wrap */
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
    c_textured = c_blend = c_depth = c_fog = c_atest = -1; c_bound = (IDirect3DTexture9 *)0;
    set_filters(0);
}

static int make_device(void)
{
    /* Depth is 1/w (reversed: 1 = near, cleared to 0, GREATEREQUAL): a floating-point buffer keeps the same relative precision at every distance,
     * where an integer one runs out near the far plane and lets a particle slightly behind a distant hill tie with it. */
    static const D3DFORMAT depth_formats[3] = { D3DFMT_D32F_LOCKABLE, D3DFMT_D24S8, D3DFMT_D16 };
    int i, soft;
    HRESULT hr = -1;
    for (i = 0; i < 3; i++) {
        for (soft = 0; soft < 2; soft++) {
            memset(&g_pp, 0, sizeof g_pp);
            g_pp.BackBufferFormat = D3DFMT_UNKNOWN;           /* windowed: use the desktop format; size 0 = the client area */
            g_pp.BackBufferWidth = g_bb_w;
            g_pp.BackBufferHeight = g_bb_h;
            g_pp.BackBufferCount = 1;
            g_pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
            g_pp.hDeviceWindow = g_wnd;
            g_pp.Windowed = 1;
            g_pp.EnableAutoDepthStencil = 1;
            g_pp.AutoDepthStencilFormat = depth_formats[i];
            g_pp.PresentationInterval = g_vsync ? D3DPRESENT_INTERVAL_ONE : D3DPRESENT_INTERVAL_IMMEDIATE;
            hr = g_d3d->lpVtbl->CreateDevice(g_d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, g_wnd,
                    (soft ? D3DCREATE_SOFTWARE_VERTEXPROCESSING : D3DCREATE_HARDWARE_VERTEXPROCESSING) | D3DCREATE_FPU_PRESERVE,
                    &g_pp, &g_dev);
            if (!HG_D3D_FAILED(hr)) { hg_log("d3d9 depth buffer "); hg_log(i == 0 ? "D32F" : i == 1 ? "D24S8" : "D16"); hg_log(soft ? ", software vertex processing\r\n" : ", hardware vertex processing\r\n"); return 0; }
            fail("CreateDevice", hr);
        }
    }
    return 1;
}

static int d3d9_init(const HgInitParams *p)
{
    { static const float mult[8] = { 1.0204f, 1.002f, 1.005f, 1.01f, 1.05f, 1.1f, 1.25f, 2.0f }; char nm[16] = "hgd3d9.obias0"; int k; void *h;
      { static const float sx_[7] = { 0, -0.5f, 0.5f, 0, 0, -0.5f, 0.5f }, sy_[7] = { 0, 0, 0, -0.5f, 0.5f, -0.5f, 0.5f }; char fn[20] = "hgd3d9.fillshift0"; int q; void *h3;
        for (q = 1; q < 7; q++) { fn[18] = (char)('0' + q); h3 = CreateFileA(fn, 0x80000000, 3, 0, 3, 0x80, 0); if (h3 != (void *)-1) { CloseHandle(h3); g_fx = sx_[q]; g_fy = sy_[q]; } } }
      { char dn[16] = "hgd3d9.dpass0"; int q; void *h5;
        for (q = 1; q <= 9; q++) { dn[14] = (char)('0' + q); h5 = CreateFileA(dn, 0x80000000, 3, 0, 3, 0x80, 0); if (h5 != (void *)-1) { CloseHandle(h5); g_dpass = q * 28; } } }
      { char an[16] = "hgd3d9.aref0"; int q; void *h4;
        for (q = 1; q <= 9; q++) { an[13] = (char)('0' + q); h4 = CreateFileA(an, 0x80000000, 3, 0, 3, 0x80, 0); if (h4 != (void *)-1) { CloseHandle(h4); g_aref = q * 16; } } }
      { static const float sl[8] = { 1.0f, 0.0f, 0.5f, 1.0f, 1.5f, 2.0f, 3.0f, 5.0f }; char sn[17] = "hgd3d9.oslope0"; int q; void *h2;
        for (q = 0; q < 8; q++) { sn[15] = (char)('0' + q); h2 = CreateFileA(sn, 0x80000000, 3, 0, 3, 0x80, 0); if (h2 != (void *)-1) { CloseHandle(h2); g_oslope = sl[q]; } } }
      for (k = 1; k < 8; k++) { nm[14] = (char)('0' + k); h = CreateFileA(nm, 0x80000000, 3, 0, 3, 0x80, 0); if (h != (void *)-1) { CloseHandle(h); g_obias = mult[k]; } } }
    g_wnd = (HWND)p->window;
    g_vsync = p->vsync;
    if (!g_wnd) { hg_log("d3d9 no window\r\n"); return 1; }
    {   /* a borderless pop-up (the 'borderless' fix's window, covering the screen) keeps its size; an asked size sets the back buffer:
         * the window's shape, scaled so the 4:3 picture in it has the asked size, and Present scales it onto the window */
        RECT c; DWORD style = (DWORD)GetWindowLongA(g_wnd, -16 /* GWL_STYLE */);
        if (p->out_w && p->out_h && (style & 0x80000000u /* WS_POPUP */) && !(style & 0x00c00000u /* WS_CAPTION */) &&
                GetClientRect(g_wnd, &c) && c.right > 0 && c.bottom > 0) {
            float ok = (float)p->out_w / HG_GAME_W, ck = (float)c.right / HG_GAME_W, f;
            if ((float)p->out_h / HG_GAME_H < ok) ok = (float)p->out_h / HG_GAME_H;
            if ((float)c.bottom / HG_GAME_H < ck) ck = (float)c.bottom / HG_GAME_H;
            f = ok / ck;
            g_bb_w = (UINT)((float)c.right * f + 0.5f); g_bb_h = (UINT)((float)c.bottom * f + 0.5f);
            hg_log("borderless window: render size scaled into it\r\n");
        }
    }
    if (p->out_w && p->out_h && !g_bb_w) {                   /* a window of the asked client size: the render resolution is the window's */
        RECT r; r.left = 0; r.top = 0; r.right = (LONG)p->out_w; r.bottom = (LONG)p->out_h;
        AdjustWindowRect(&r, (DWORD)GetWindowLongA(g_wnd, -16 /* GWL_STYLE */), 0);
        SetWindowPos(g_wnd, (HWND)0, 0, 0, r.right - r.left, r.bottom - r.top, 0x0002 | 0x0004 | 0x0010);   /* NOMOVE | NOZORDER | NOACTIVATE */
    }
    g_d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!g_d3d) { hg_log("d3d9 Direct3DCreate9 failed\r\n"); return 1; }
    if (make_device()) { g_d3d->lpVtbl->Release(g_d3d); g_d3d = 0; return 1; }
    layout();
    apply_state();
    queries_create();
    hg_log("d3d9 device created, backbuffer "); hg_log_hex(g_pp.BackBufferWidth); hg_log(" x "); hg_log_hex(g_pp.BackBufferHeight);
    hg_log(", scale x1000 "); hg_log_hex((uint32_t)(g_scale * 1000.0f)); hg_log("\r\n");
    return 0;
}

static void d3d9_shutdown(void)
{
    queries_release();
    lights_release();
    if (g_overlay) { g_overlay->lpVtbl->Release(g_overlay); g_overlay = 0; }
    if (g_dev) { g_dev->lpVtbl->Release(g_dev); g_dev = 0; }
    if (g_d3d) { g_d3d->lpVtbl->Release(g_d3d); g_d3d = 0; }
}

static int d3d9_restore(void)
{
    HRESULT hr;
    if (!g_dev) return 1;
    hr = DEV->TestCooperativeLevel(g_dev);
    if (!HG_D3D_FAILED(hr)) { g_lost = 0; return 0; }
    if (hr != D3DERR_DEVICENOTRESET) return 1;               /* still lost, try again next frame */
    queries_release();                                       /* default-pool objects must go before a Reset */
    lights_release();
    hr = DEV->Reset(g_dev, &g_pp);                           /* managed textures survive a Reset */
    if (HG_D3D_FAILED(hr)) { fail("Reset", hr); return 1; }
    layout(); apply_state(); queries_create(); g_lost = 0;
    return 0;
}

/* ---- textures ------------------------------------------------------------------------------------------------ */
static int fill(IDirect3DTexture9 *t, uint32_t w, uint32_t h, const uint32_t *argb)
{
    D3DLOCKED_RECT lr; uint32_t y;
    HRESULT hr = t->lpVtbl->LockRect(t, 0, &lr, (const RECT *)0, 0);
    if (HG_D3D_FAILED(hr)) { fail("LockRect", hr); return 1; }
    for (y = 0; y < h; y++) memcpy((uint8_t *)lr.pBits + (size_t)y * (size_t)lr.Pitch, argb + (size_t)y * w, (size_t)w * 4);
    t->lpVtbl->UnlockRect(t, 0);
    t->lpVtbl->GenerateMipSubLevels(t);                      /* no-op unless the texture is auto-generating */
    return 0;
}

static HgTex *d3d9_tex_create(uint32_t w, uint32_t h, const uint32_t *argb, uint32_t flags)
{
    IDirect3DTexture9 *t = 0;
    HRESULT hr;
    if (!g_dev) return (HgTex *)0;
    if (flags & HG_TEX_NO_MIPS) hr = -1;                     /* straight to the single level */
    else hr = DEV->CreateTexture(g_dev, w, h, 0, D3DUSAGE_AUTOGENMIPMAP, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, (HANDLE *)0);
    if (HG_D3D_FAILED(hr)) {                                 /* no automatic mips: a single level */
        hr = DEV->CreateTexture(g_dev, w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &t, (HANDLE *)0);
        if (HG_D3D_FAILED(hr)) { fail("CreateTexture", hr); return (HgTex *)0; }
    }
    if (fill(t, w, h, argb)) { t->lpVtbl->Release(t); return (HgTex *)0; }
    return (HgTex *)t;
}

static int d3d9_tex_update(HgTex *t, uint32_t w, uint32_t h, const uint32_t *argb)
{
    return fill((IDirect3DTexture9 *)t, w, h, argb);
}

static void d3d9_tex_destroy(HgTex *t) { if (t) ((IDirect3DTexture9 *)t)->lpVtbl->Release((IDirect3DTexture9 *)t); }

/* ---- drawing -------------------------------------------------------------------------------------------------- */
static void d3d9_set_fog_color(uint32_t rgb)
{
    g_fog_color = 0xff000000u | (rgb & 0x00ffffffu);
    if (g_dev) DEV->SetRenderState(g_dev, D3DRS_FOGCOLOR, g_fog_color);
}

static void set_mipmaps_impl(int on)
{
    g_mips = on;
    if (g_dev) set_filters(c_point > 0);
}

static void ensure_scene(void)
{
    if (!g_scene) { TRY(DEV->BeginScene(g_dev), "BeginScene"); g_scene = 1; }
}

static void set_state_fog(int fog)
{
    if (fog != c_fog) { DEV->SetRenderState(g_dev, D3DRS_FOGENABLE, fog); c_fog = fog; s_states++; }
}

static void set_state(int textured, int blend, int depth, IDirect3DTexture9 *tex)
{
    if (textured != c_textured) {
        DEV->SetTextureStageState(g_dev, 0, D3DTSS_COLOROP, textured ? D3DTOP_MODULATE : D3DTOP_SELECTARG2);
        DEV->SetTextureStageState(g_dev, 0, D3DTSS_ALPHAOP, textured ? D3DTOP_MODULATE : D3DTOP_SELECTARG2);
        c_textured = textured;
    }
    if (textured && tex != c_bound) { DEV->SetTexture(g_dev, 0, (IDirect3DBaseTexture9 *)tex); c_bound = tex; s_binds++; }
    if (blend != c_blend) { DEV->SetRenderState(g_dev, D3DRS_ALPHABLENDENABLE, blend); c_blend = blend; s_states++; }
    /* Fully transparent texels (the chroma key, alpha-palette holes) must not write depth: the Voodoo throws a keyed texel away before the depth test, while
     * a blended pixel with alpha 0 would still write the sprite's depth and block everything drawn after it (a screen-space sprite at w = 1 hid a whole ridge). */
    { int at = (textured && blend) ? 1 : 0; if (at != c_atest) { DEV->SetRenderState(g_dev, D3DRS_ALPHATESTENABLE, at); c_atest = at; s_states++; } }
    if (textured && blend) DEV->SetRenderState(g_dev, D3DRS_ALPHAREF, g_aref);
    if (depth != c_depth) {
        DEV->SetRenderState(g_dev, D3DRS_ZENABLE, depth != 0);
        DEV->SetRenderState(g_dev, D3DRS_ZWRITEENABLE, depth == 1);
        c_depth = depth; s_states++;
    }
}

/* Game pixels to window pixels, with the half-pixel shift Direct3D 9 needs for pre-transformed vertices. */
static void scale_vertices(HgVertex *out, const HgVertex *in, uint32_t n)
{
    uint32_t i;
    for (i = 0; i < n; i++) {
        out[i] = in[i];
        out[i].x = g_ox + in[i].x * g_scale - 0.5f;
        out[i].y = g_oy + in[i].y * g_scale - 0.5f;
        out[i].z = in[i].rhw > 1.0f ? 1.0f : (in[i].rhw > 0.0f ? in[i].rhw : 0.0f);   /* depth = 1/w itself: exact when interpolated; infinity is 0, the far end */
        if (out[i].rhw == 0.0f) out[i].rhw = 1.0f;      /* geometry at infinity (the sky fill); rhw 0 is undefined in D3D */
    }
}

static void d3d9_draw_fan(const HgVertex *v, uint32_t n, HgTex *tex, const HgDrawState *st)
{
    HgVertex tmp[MAX_POLY];
    if (g_lost || !g_dev || n < 3 || n > MAX_POLY) return;
    ensure_scene();
    set_state(tex != 0, st->blend == HG_BLEND_ALPHA, st->depth, (IDirect3DTexture9 *)tex);
    set_state_fog(st->fog != 0);
    scale_vertices(tmp, v, n);
    if (g_fx != 0.0f || g_fy != 0.0f) { uint32_t q; for (q = 0; q < n; q++) { tmp[q].x += g_fx; tmp[q].y += g_fy; } }
    s_draws++; s_verts += n;
    if (st->depth == 1 && st->blend == HG_BLEND_NONE && g_nrec < REC_DRAWS && g_nrecv + n <= REC_VERTS) {   /* remember the opaque polygons for the lighting pass */
        memcpy(&g_rec[g_nrecv], tmp, (size_t)n * sizeof(HgVertex));
        g_rec_start[g_nrec] = (uint16_t)g_nrecv; g_rec_n[g_nrec] = (uint16_t)n; g_nrec++; g_nrecv += n;
    }
    TRY(DEV->DrawPrimitiveUP(g_dev, D3DPT_TRIANGLEFAN, n - 2, tmp, sizeof(HgVertex)), "DrawPrimitiveUP");
    if (tex && st->pad == 2) {
        /* A blended sprite only tests depth (the engine sorts them back to front), but its solid texels (alpha 0.5 or more) also write it, so a sprite hides what is
         * behind it (the far wireframes under the dust) without its nearly transparent edges blocking the sprites and lights behind. A second, colourless pass. */
        DEV->SetRenderState(g_dev, D3DRS_COLORWRITEENABLE, 0);
        DEV->SetRenderState(g_dev, D3DRS_ALPHABLENDENABLE, 0);
        DEV->SetRenderState(g_dev, D3DRS_ZENABLE, 1);
        DEV->SetRenderState(g_dev, D3DRS_ZWRITEENABLE, 1);
        DEV->SetRenderState(g_dev, D3DRS_ALPHATESTENABLE, 1);
        DEV->SetRenderState(g_dev, D3DRS_ALPHAREF, g_dpass);
        DEV->SetRenderState(g_dev, D3DRS_ALPHAFUNC, D3DCMP_GREATEREQUAL);
        TRY(DEV->DrawPrimitiveUP(g_dev, D3DPT_TRIANGLEFAN, n - 2, tmp, sizeof(HgVertex)), "DrawPrimitiveUP depth pass");
        DEV->SetRenderState(g_dev, D3DRS_COLORWRITEENABLE, 0xf);
        DEV->SetRenderState(g_dev, D3DRS_ALPHAREF, g_aref);
        DEV->SetRenderState(g_dev, D3DRS_ALPHAFUNC, D3DCMP_GREATER);
        c_blend = c_depth = c_atest = -1;                 /* the cached states are stale now */
    }
}

/* Outlines and points lie exactly on the surface of the polygon they belong to (the damage wireframe on a model, the wireframe
 * over a low-light fill). With a depth test they compete with that surface for the same depth values and lose in patches, so
 * they are pulled slightly toward the camera: 2% of their w, which is far above the depth buffer's resolution. */
/* How fast 1/w changes across the polygon's own surface, in 1/w per game pixel (|d/dx| + |d/dy|): 1/w is linear in screen space, so three vertices give the
 * plane. Near the horizon the ground's 1/w changes by several percent per pixel, so a line along an edge and the fill beside it differ in depth by more than any
 * fixed percentage covers, and the line comes out dashed. The bias adds this much, like a slope-scaled depth bias. Uses the triple of vertices with the most area. */
static float depth_slope(const HgVertex *v, uint32_t n)
{
    uint32_t i; float best = 0.0f, slope = 0.0f;
    for (i = 1; i + 1 < n; i++) {
        float bx = v[i].x - v[0].x, by = v[i].y - v[0].y, cx = v[i + 1].x - v[0].x, cy = v[i + 1].y - v[0].y;
        float det = bx * cy - cx * by, ad = det < 0.0f ? -det : det;
        if (ad > best && ad > 1e-3f) {
            float br = v[i].rhw - v[0].rhw, cr = v[i + 1].rhw - v[0].rhw;
            float gx = (br * cy - cr * by) / det, gy = (cr * bx - br * cx) / det;
            best = ad; slope = (gx < 0.0f ? -gx : gx) + (gy < 0.0f ? -gy : gy);
        }
    }
    return slope;
}

static void bias_toward_camera(HgVertex *v, uint32_t n, float slope)
{
    uint32_t i;
    /* Depth is 1/w (larger = nearer): 2% nearer in w is 1/w times 1.0204, plus the surface's own change over g_oslope pixels. */
    for (i = 0; i < n; i++) { float z = v[i].z * g_obias + slope * g_oslope; v[i].z = z > 1.0f ? 1.0f : z; }
}

/* Outline of a polygon (the wireframes) and points: untextured, one pixel wide. */
static void d3d9_draw_outline(const HgVertex *v, uint32_t n, const HgDrawState *st)
{
    HgVertex tmp[MAX_POLY + 1];
    if (g_lost || !g_dev || n < 2 || n > MAX_POLY) return;
    ensure_scene();
    set_state(0, 0, st->depth, (IDirect3DTexture9 *)0);
    set_state_fog(0);                                 /* the plugin turns fog off around outlines */
    scale_vertices(tmp, v, n);
    if (st->pad == 3) { uint32_t q; for (q = 0; q < n; q++) { float z = tmp[q].z * 1.25f; tmp[q].z = z > 1.0f ? 1.0f : z; } }   /* hidefar: 25% nearer in 1/w, test only */
    else if (st->pad) { uint32_t q; for (q = 0; q < n; q++) { float z = tmp[q].z * 1000.0f; tmp[q].z = z > 1.0f ? 1.0f : z; } }   /* sprite-only occlusion: see hgd3d9.c */
    else bias_toward_camera(tmp, n, n >= 3 ? depth_slope(v, n) : 0.0f);
    tmp[n] = tmp[0];                                  /* close the loop */
    s_draws++; s_verts += n;
    TRY(DEV->DrawPrimitiveUP(g_dev, D3DPT_LINESTRIP, n, tmp, sizeof(HgVertex)), "DrawPrimitiveUP lines");
}

static void d3d9_draw_points(const HgVertex *v, uint32_t n, const HgDrawState *st)
{
    HgVertex tmp[MAX_POLY];
    if (g_lost || !g_dev || n < 1 || n > MAX_POLY) return;
    ensure_scene();
    set_state(0, 0, st->depth, (IDirect3DTexture9 *)0);
    set_state_fog(0);
    scale_vertices(tmp, v, n);
    bias_toward_camera(tmp, n, 0.0f);
    s_draws++; s_verts += n;
    TRY(DEV->DrawPrimitiveUP(g_dev, D3DPT_POINTLIST, n, tmp, sizeof(HgVertex)), "DrawPrimitiveUP points");
}

static void d3d9_clear_depth(void)
{
    g_nrec = g_nrecv = 0;
    if (g_lost || !g_dev) return;
    TRY(DEV->Clear(g_dev, 0, (const D3DRECT *)0, D3DCLEAR_ZBUFFER, D3DCOLOR_ARGB(255, 0, 0, 0), 0.0f, 0), "Clear depth");
}

/* The 2D layer: RGB565 from the engine, converted to ARGB (the key value becomes transparent) in a 1024x512 texture and
 * drawn as one quad with point sampling so the HUD stays crisp. */
static void d3d9_draw_overlay(const HgOverlay *o)
{
    D3DLOCKED_RECT lr; uint32_t x, y; HRESULT hr;
    HgVertex q[4], tmp[4];
    float u1 = (float)HG_GAME_W / OVERLAY_W, v1 = (float)HG_GAME_H / OVERLAY_H;
    if (g_lost || !g_dev) return;
    if (!g_overlay) {
        hr = DEV->CreateTexture(g_dev, OVERLAY_W, OVERLAY_H, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &g_overlay, (HANDLE *)0);
        if (HG_D3D_FAILED(hr)) { fail("CreateTexture overlay", hr); g_overlay = 0; return; }
    }
    hr = g_overlay->lpVtbl->LockRect(g_overlay, 0, &lr, (const RECT *)0, 0);
    if (HG_D3D_FAILED(hr)) { fail("LockRect overlay", hr); return; }
    for (y = 0; y < HG_GAME_H; y++) {
        const uint16_t *src = (const uint16_t *)((const uint8_t *)o->pixels + (size_t)y * o->pitch);
        uint32_t *dst = (uint32_t *)((uint8_t *)lr.pBits + (size_t)y * (size_t)lr.Pitch);
        for (x = 0; x < HG_GAME_W; x++) {
            uint32_t p = src[x], r = (p >> 11) & 31, g = (p >> 5) & 63, b = p & 31;
            uint32_t a = (o->key >= 0 && p == (uint32_t)o->key) ? 0u : 255u;
            dst[x] = (a << 24) | (((r << 3) | (r >> 2)) << 16) | (((g << 2) | (g >> 4)) << 8) | ((b << 3) | (b >> 2));
        }
    }
    g_overlay->lpVtbl->UnlockRect(g_overlay, 0);

    q[0].x = 0.0f;         q[0].y = 0.0f;         q[0].u = 0.0f; q[0].v = 0.0f;
    q[1].x = HG_GAME_W;    q[1].y = 0.0f;         q[1].u = u1;   q[1].v = 0.0f;
    q[2].x = HG_GAME_W;    q[2].y = HG_GAME_H;    q[2].u = u1;   q[2].v = v1;
    q[3].x = 0.0f;         q[3].y = HG_GAME_H;    q[3].u = 0.0f; q[3].v = v1;
    for (x = 0; x < 4; x++) { q[x].z = 0.0f; q[x].rhw = 1.0f; q[x].color = 0xffffffffu; q[x].specular = 0xff000000u; }
    ensure_scene();
    set_filters(1);
    set_state(1, 1, 0, g_overlay);
    set_state_fog(0);
    scale_vertices(tmp, q, 4);
    TRY(DEV->DrawPrimitiveUP(g_dev, D3DPT_TRIANGLEFAN, 2, tmp, sizeof(HgVertex)), "DrawPrimitiveUP overlay");
    set_filters(0);
}

static void d3d9_present(void)
{
    HRESULT hr;
    if (!g_dev) return;
    if (g_lost && d3d9_restore()) return;
    if (g_scene) { TRY(DEV->EndScene(g_dev), "EndScene"); g_scene = 0; }
    g_nrec = g_nrecv = 0;
    hr = DEV->Present(g_dev, (const RECT *)0, (const RECT *)0, (HWND)0, (const RGNDATA *)0);
    if (hr == D3DERR_DEVICELOST) { g_lost = 1; return; }
    if (HG_D3D_FAILED(hr)) fail("Present", hr);
    if (g_qok) {                                             /* how many earlier frames are still unfinished? */
        uint32_t i, inflight = 0;
        for (i = 0; i < NQ; i++) if (g_qp[i]) {
            if (g_q[i]->lpVtbl->GetData(g_q[i], (void *)0, 0, 0) == D3D_OK) g_qp[i] = 0; else inflight++;
        }
        s_fl_sum += inflight; if (inflight > s_fl_max) s_fl_max = inflight;
        if (!g_qp[g_qi]) { g_q[g_qi]->lpVtbl->Issue(g_q[g_qi], D3DISSUE_END); g_qp[g_qi] = 1; g_qi = (g_qi + 1) % NQ; }
    }
    if (++s_frames == 240) {
        hg_log("d3d9 per frame: draws "); hg_log_dec(s_draws / 240); hg_log(", texture binds "); hg_log_dec(s_binds / 240);
        hg_log(", state changes "); hg_log_dec(s_states / 240); hg_log(", vertices "); hg_log_dec(s_verts / 240);
        hg_log("; frames in flight avg x0.1 "); hg_log_dec(s_fl_sum * 10 / 240); hg_log(", max "); hg_log_dec(s_fl_max); hg_log("\r\n");
        s_frames = s_draws = s_binds = s_states = s_verts = 0; s_fl_sum = s_fl_max = 0;
    }
    /* RefreshDisplay of the 3Dfx plugin swaps, then clears colour and depth */
    TRY(DEV->Clear(g_dev, 0, (const D3DRECT *)0, D3DCLEAR_TARGET | D3DCLEAR_ZBUFFER, D3DCOLOR_ARGB(255, 0, 0, 0), 0.0f, 0), "Clear");
}

/* Back buffer to a 24-bit BMP. 2880x2160 at most (a static buffer, no CRT allocator). */
static uint8_t g_bmp[54 + 2880 * 2160 * 3];
static int d3d9_screenshot(const char *path)
{
    IDirect3DSurface9 *bb = 0, *sys = 0;
    D3DLOCKED_RECT lr; HRESULT hr; uint32_t w, h, x, y, rowbytes, n; uint8_t *o; int rc = 1;
    if (!g_dev || g_lost) return 1;
    if (g_scene) { TRY(DEV->EndScene(g_dev), "EndScene"); g_scene = 0; }
    w = g_pp.BackBufferWidth; h = g_pp.BackBufferHeight;
    if (!w || !h || w > 2880 || h > 2160) { hg_log("screenshot: size not supported\r\n"); return 1; }
    hr = DEV->GetBackBuffer(g_dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &bb);
    if (HG_D3D_FAILED(hr)) { fail("GetBackBuffer", hr); return 1; }
    hr = DEV->CreateOffscreenPlainSurface(g_dev, w, h, g_pp.BackBufferFormat, D3DPOOL_SYSTEMMEM, &sys, (HANDLE *)0);
    if (HG_D3D_FAILED(hr)) { fail("CreateOffscreenPlainSurface", hr); bb->lpVtbl->Release(bb); return 1; }
    hr = DEV->GetRenderTargetData(g_dev, bb, sys);
    if (HG_D3D_FAILED(hr)) { fail("GetRenderTargetData", hr); goto done; }
    hr = sys->lpVtbl->LockRect(sys, &lr, (const RECT *)0, D3DLOCK_READONLY);
    if (HG_D3D_FAILED(hr)) { fail("LockRect screenshot", hr); goto done; }
    rowbytes = (w * 3 + 3) & ~3u; n = 54 + rowbytes * h;
    memset(g_bmp, 0, 54);
    g_bmp[0] = 'B'; g_bmp[1] = 'M';
    *(uint32_t *)(g_bmp + 2) = n; *(uint32_t *)(g_bmp + 10) = 54; *(uint32_t *)(g_bmp + 14) = 40;
    *(uint32_t *)(g_bmp + 18) = w; *(uint32_t *)(g_bmp + 22) = h; g_bmp[26] = 1; g_bmp[28] = 24;
    for (y = 0; y < h; y++) {                      /* BMP rows run bottom to top; the surface is 32 bits per pixel */
        const uint8_t *src = (const uint8_t *)lr.pBits + (size_t)y * (size_t)lr.Pitch;
        o = g_bmp + 54 + (size_t)(h - 1 - y) * rowbytes;
        for (x = 0; x < w; x++) { o[3 * x] = src[4 * x]; o[3 * x + 1] = src[4 * x + 1]; o[3 * x + 2] = src[4 * x + 2]; }
    }
    sys->lpVtbl->UnlockRect(sys);
    rc = hg_write_file(path, g_bmp, n);
done:
    sys->lpVtbl->Release(sys); bb->lpVtbl->Release(bb);
    return rc;
}

/* ---- point lights ----------------------------------------------------------------------------------------------- */
typedef struct WVert { float x, y, z, rhw, w; } WVert;
#define FVF_W (D3DFVF_XYZRHW | D3DFVF_TEX1)

static int lights_init(void)
{
    HRESULT hr;
    if (g_lights_state) return g_lights_state < 0;
    g_lights_state = -1;
    hr = DEV->CreateTexture(g_dev, g_pp.BackBufferWidth, g_pp.BackBufferHeight, 1, D3DUSAGE_RENDERTARGET, D3DFMT_R32F, D3DPOOL_DEFAULT, &g_wtex, (HANDLE *)0);
    if (HG_D3D_FAILED(hr)) { fail("CreateTexture R32F", hr); goto bad; }
    hr = g_wtex->lpVtbl->GetSurfaceLevel(g_wtex, 0, &g_wsurf);
    if (HG_D3D_FAILED(hr)) { fail("GetSurfaceLevel", hr); goto bad; }
    /* Discard must be FALSE for a lockable format (a real driver answers INVALIDCALL, Wine does not). Try the device's own format, then D24S8. */
    hr = DEV->CreateDepthStencilSurface(g_dev, g_pp.BackBufferWidth, g_pp.BackBufferHeight, g_pp.AutoDepthStencilFormat, D3DMULTISAMPLE_NONE, 0, 0, &g_wdepth, (HANDLE *)0);
    if (HG_D3D_FAILED(hr)) { fail("CreateDepthStencilSurface", hr); hr = DEV->CreateDepthStencilSurface(g_dev, g_pp.BackBufferWidth, g_pp.BackBufferHeight, D3DFMT_D24S8, D3DMULTISAMPLE_NONE, 0, 0, &g_wdepth, (HANDLE *)0); }
    if (HG_D3D_FAILED(hr)) { fail("CreateDepthStencilSurface D24S8", hr); goto bad; }
    hr = DEV->CreatePixelShader(g_dev, (const DWORD *)g_w_ps, &g_psw);
    if (HG_D3D_FAILED(hr)) { fail("CreatePixelShader w", hr); goto bad; }
    hr = DEV->CreatePixelShader(g_dev, (const DWORD *)g_light_ps, &g_psl);
    if (HG_D3D_FAILED(hr)) { fail("CreatePixelShader light", hr); goto bad; }
    g_lights_state = 1; hg_log("d3d9 lighting pass ready\r\n");
    return 0;
bad:
    lights_release(); g_lights_state = -1;
    return 1;
}

static void after_pass(void)
{
    apply_viewport();
    DEV->SetPixelShader(g_dev, (IDirect3DPixelShader9 *)0);
    DEV->SetFVF(g_dev, D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_SPECULAR | D3DFVF_TEX1);
    DEV->SetTexture(g_dev, 0, (IDirect3DBaseTexture9 *)0);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_ADDRESSU, D3DTADDRESS_WRAP);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_ADDRESSV, D3DTADDRESS_WRAP);
    c_textured = c_blend = c_depth = c_fog = c_atest = -1; c_bound = (IDirect3DTexture9 *)0;
    set_filters(0);
}

static void depth_pass(void)
{
    IDirect3DSurface9 *rt0 = 0, *ds0 = 0; uint32_t i, k;
    WVert bg[4], tmp[MAX_POLY];
    float W = (float)g_pp.BackBufferWidth, H = (float)g_pp.BackBufferHeight;
    if (g_wvalid_n == g_nrec) return;
    DEV->GetRenderTarget(g_dev, 0, &rt0);
    DEV->GetDepthStencilSurface(g_dev, &ds0);
    DEV->SetRenderTarget(g_dev, 0, g_wsurf);
    DEV->SetDepthStencilSurface(g_dev, g_wdepth);
    DEV->Clear(g_dev, 0, (const D3DRECT *)0, D3DCLEAR_ZBUFFER, 0, 0.0f, 0);
    DEV->SetPixelShader(g_dev, g_psw);
    DEV->SetFVF(g_dev, FVF_W);
    DEV->SetRenderState(g_dev, D3DRS_ALPHABLENDENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ALPHATESTENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_FOGENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ZENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ZWRITEENABLE, 0);
    bg[0].x = -0.5f; bg[0].y = -0.5f; bg[1].x = W - 0.5f; bg[1].y = -0.5f; bg[2].x = W - 0.5f; bg[2].y = H - 0.5f; bg[3].x = -0.5f; bg[3].y = H - 0.5f;
    for (i = 0; i < 4; i++) { bg[i].z = 0.0f; bg[i].rhw = 1.0f; bg[i].w = 1.0e9f; }
    DEV->DrawPrimitiveUP(g_dev, D3DPT_TRIANGLEFAN, 2, bg, sizeof(WVert));
    DEV->SetRenderState(g_dev, D3DRS_ZENABLE, 1);
    DEV->SetRenderState(g_dev, D3DRS_ZWRITEENABLE, 1);
    for (i = 0; i < g_nrec; i++) {
        uint32_t n = g_rec_n[i];
        for (k = 0; k < n; k++) {
            const HgVertex *v = &g_rec[g_rec_start[i] + k];
            tmp[k].x = v->x; tmp[k].y = v->y; tmp[k].z = v->z; tmp[k].rhw = v->rhw; tmp[k].w = 1.0f / v->rhw;
        }
        DEV->DrawPrimitiveUP(g_dev, D3DPT_TRIANGLEFAN, n - 2, tmp, sizeof(WVert));
    }
    DEV->SetRenderTarget(g_dev, 0, rt0);
    DEV->SetDepthStencilSurface(g_dev, ds0);
    if (rt0) rt0->lpVtbl->Release(rt0);
    if (ds0) ds0->lpVtbl->Release(ds0);
    after_pass();
    g_wvalid_n = g_nrec;
}

static int d3d9_draw_light(const HgLight *l)
{
    struct { float x, y, z, rhw, u, v; } q[4];
    float c0[4], c1[4], c2[4], c3[4], c4[4], c5[4], W, H, sx0, sy0, sx1, sy1; uint32_t i;
    if (g_lost || !g_dev || lights_init()) return 1;
    ensure_scene();
    depth_pass();
    W = (float)g_pp.BackBufferWidth; H = (float)g_pp.BackBufferHeight;
    sx0 = g_ox + l->x0 * g_scale; sx1 = g_ox + l->x1 * g_scale; sy0 = g_oy + l->y0 * g_scale; sy1 = g_oy + l->y1 * g_scale;
    if (sx0 < 0) sx0 = 0; if (sy0 < 0) sy0 = 0; if (sx1 > W) sx1 = W; if (sy1 > H) sy1 = H;
    if (sx1 <= sx0 || sy1 <= sy0) return 0;
    c0[0] = 320.0f; c0[1] = 240.0f; c0[2] = 1.0f / 320.0f; c0[3] = 0.0f;
    c1[0] = l->pos[0]; c1[1] = l->pos[1]; c1[2] = l->pos[2]; c1[3] = 0.0f;
    c2[0] = l->inv_radius; c2[1] = l->amp; c2[2] = 1.0f; c2[3] = 175.0f;     /* the cockpit weapon is drawn at w 145 to 180 */
    c5[0] = 1.0f / 75.0f; c5[1] = c5[2] = c5[3] = 0.0f;
    c3[0] = l->col[0]; c3[1] = l->col[1]; c3[2] = l->col[2]; c3[3] = 1.0f;
    c4[0] = W / g_scale; c4[1] = -g_ox / g_scale; c4[2] = H / g_scale; c4[3] = -g_oy / g_scale;
    DEV->SetPixelShader(g_dev, g_psl);
    DEV->SetPixelShaderConstantF(g_dev, 0, c0, 1); DEV->SetPixelShaderConstantF(g_dev, 1, c1, 1); DEV->SetPixelShaderConstantF(g_dev, 2, c2, 1);
    DEV->SetPixelShaderConstantF(g_dev, 3, c3, 1); DEV->SetPixelShaderConstantF(g_dev, 4, c4, 1); DEV->SetPixelShaderConstantF(g_dev, 5, c5, 1);
    DEV->SetTexture(g_dev, 0, (IDirect3DBaseTexture9 *)g_wtex);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_MINFILTER, D3DTEXF_POINT); DEV->SetSamplerState(g_dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
    DEV->SetSamplerState(g_dev, 0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP); DEV->SetSamplerState(g_dev, 0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
    DEV->SetFVF(g_dev, FVF_W);
    DEV->SetRenderState(g_dev, D3DRS_ALPHABLENDENABLE, 1);
    DEV->SetRenderState(g_dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    DEV->SetRenderState(g_dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    DEV->SetRenderState(g_dev, D3DRS_ALPHATESTENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_FOGENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ZENABLE, 0);
    DEV->SetRenderState(g_dev, D3DRS_ZWRITEENABLE, 0);
    q[0].x = sx0 - 0.5f; q[0].y = sy0 - 0.5f; q[0].u = sx0 / W; q[0].v = sy0 / H;
    q[1].x = sx1 - 0.5f; q[1].y = sy0 - 0.5f; q[1].u = sx1 / W; q[1].v = sy0 / H;
    q[2].x = sx1 - 0.5f; q[2].y = sy1 - 0.5f; q[2].u = sx1 / W; q[2].v = sy1 / H;
    q[3].x = sx0 - 0.5f; q[3].y = sy1 - 0.5f; q[3].u = sx0 / W; q[3].v = sy1 / H;
    for (i = 0; i < 4; i++) { q[i].z = 0.0f; q[i].rhw = 1.0f; }
    s_draws++;
    TRY(DEV->DrawPrimitiveUP(g_dev, D3DPT_TRIANGLEFAN, 2, q, sizeof q[0]), "DrawPrimitiveUP light");
    after_pass();
    return 0;
}

const HgBackend hg_backend_d3d9 = {
    "d3d9", d3d9_init, d3d9_shutdown, d3d9_restore, d3d9_tex_create, d3d9_tex_update, d3d9_tex_destroy,
    d3d9_draw_outline, d3d9_draw_points, d3d9_set_fog_color, set_mipmaps_impl, d3d9_draw_fan, d3d9_clear_depth, d3d9_draw_overlay, d3d9_present, d3d9_screenshot, d3d9_draw_light
};
