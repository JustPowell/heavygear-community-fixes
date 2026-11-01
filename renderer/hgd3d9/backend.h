/* backend.h - the internal interface between the Heavy Gear renderer plugin and a GPU backend.
 *
 * The plugin (hgd3d9.c) speaks the game's plugin API (docs/research/renderer-interface.md). It turns each `Render` call
 * into one polygon of HgVertex and calls the backend; a backend knows nothing about the game's structures.
 * Backends: null_backend.c (draws nothing, for testing the plugin) and d3d9.c.
 *
 * Conventions
 *  - One thread: every call comes from the game's render thread.
 *  - Functions that can fail return 0 on success and non-zero on failure, unless stated otherwise.
 *  - Coordinates are in *game pixels*: x in 0..game_w, y in 0..game_h (640x480). The backend maps them to the output
 *    (scaling, and pillarboxing when the output is not 4:3); callers never see the output size.
 *  - Colours and texels are 0xAARRGGBB in a uint32_t (bytes B, G, R, A in memory).
 *  - Includes only <stdint.h>, so the pure parts of the plugin can be built and tested natively.
 */
#ifndef HG_BACKEND_H
#define HG_BACKEND_H

#include <stdint.h>

#define HG_GAME_W 640
#define HG_GAME_H 480

typedef struct HgTex HgTex;   /* opaque, owned by the backend */
#define HG_TEX_NO_MIPS 1u

/* Provided by the plugin (hgd3d9.c) for the backends and the texture cache. */
void hg_log(const char *s);                 /* append to hgd3d9.log (no newline added) */
void hg_log_hex(uint32_t v);                /* append "0x" and 8 hex digits */
void hg_log_dec(uint32_t v);                /* append a decimal number */
int  hg_readable(const void *p, uint32_t bytes);   /* non-zero if the memory can be read */
int  hg_write_file(const char *path, const void *data, uint32_t bytes);   /* 0 on success */

/* One vertex as the game's projection left it, with the light and colour already applied by convert.c.
 * 32 bytes, laid out like D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_SPECULAR | D3DFVF_TEX1, so the D3D9 backend can draw it as is. */
typedef struct HgVertex {
    float    x, y;     /* game pixels */
    float    z;        /* depth in 0..1, 0 = near (convert.c: 1 - 1/w). The d3d9 backend ignores it and uses rhw itself, as a floating-point reversed depth */
    float    rhw;      /* 1 / w, 0 for geometry at infinity (the sky and ground fill) */
    uint32_t color;    /* 0xAARRGGBB, lit */
    uint32_t specular; /* the alpha byte is the fog factor for pre-transformed vertices: 0xFF = no fog, 0 = fully fogged (the engine's fog byte) */
    float    u, v;     /* texture coordinates, 0..1 */
} HgVertex;

enum HgBlend {
    HG_BLEND_NONE  = 0,   /* opaque */
    HG_BLEND_ALPHA = 1    /* src alpha, one minus src alpha */
};

typedef struct HgDrawState {
    uint8_t blend;     /* enum HgBlend */
    uint8_t fog;       /* 0 = off, 1 = on: blend toward the fog colour by each vertex's specular alpha */
    uint8_t depth;     /* 0 = no depth test or write, 1 = test and write, 2 = test only */
    uint8_t pad;
} HgDrawState;

/* The 2D layer: the engine writes it through LockDisplay every frame. On the 3Dfx path the lock is grLfbLock(write only,
 * back buffer, RGB565), so the layer is 16 bits per pixel, not palettised. The plugin owns the buffer and hands it to the
 * backend once per frame, after the 3D polygons and before present(). */
typedef struct HgOverlay {
    const uint16_t *pixels;        /* RGB565, game_h rows of `pitch` bytes */
    uint32_t        pitch;         /* bytes per row */
    int             key;           /* a 16-bit value to leave untouched (not drawn), or -1 for none; the engine only writes
                                      HUD pixels, so untouched pixels are 0 and a key of 0 is the likely rule. Still to be tested. */
} HgOverlay;

/* A point light for the lighting pass (hgd3d9's replacement for the game's flat ground glow). Camera space: x right, y down, z = w (the eye depth),
 * the game's projection (centre 320, 240; focal length 320 pixels). The light adds `col` with alpha amp * max(0, 1 - distance / radius) to every
 * surface within reach, so it lights slopes, rocks and gears alike. The backend needs the opaque geometry of the frame to find each pixel's depth. */
typedef struct HgLight {
    float pos[3];
    float inv_radius;
    float amp;
    float col[3];
    float x0, y0, x1, y1;      /* game-pixel rectangle that covers the light's reach */
} HgLight;

typedef struct HgInitParams {
    void    *window;           /* HWND of the game's window; may be NULL for the null backend */
    uint32_t out_w, out_h;     /* output size in pixels; 0 = the window's client size */
    uint32_t samples;          /* multisample count, 0 or 1 = off */
    int      vsync;
} HgInitParams;

typedef struct HgBackend {
    const char *name;

    int  (*init)(const HgInitParams *p);
    void (*shutdown)(void);

    /* After the display was lost (Alt-Tab, mode change). Textures created with tex_create stay valid:
     * backends must keep them in memory the device can restore (D3D9: the managed pool) or recreate them. */
    int  (*restore)(void);

    /* Textures. `argb` has w*h texels, base level only; the backend generates the mip chain unless flags has HG_TEX_NO_MIPS (sparse detail such as
     * the night stars, which averaging would wipe out). w and h are powers of two,
     * 1 to 256. tex_update replaces the pixels of a texture of the same size (a palette change). tex_destroy accepts NULL. */
    HgTex *(*tex_create)(uint32_t w, uint32_t h, const uint32_t *argb, uint32_t flags);
    int    (*tex_update)(HgTex *t, uint32_t w, uint32_t h, const uint32_t *argb);
    void   (*tex_destroy)(HgTex *t);

    /* The outline of a convex polygon as lines (prims 18 and 19, the wireframes): n edges, closed, Gouraud colour. */
    void (*draw_outline)(const HgVertex *v, uint32_t n, const HgDrawState *st);

    /* n points, one pixel each, in each vertex's colour (prim 20). */
    void (*draw_points)(const HgVertex *v, uint32_t n, const HgDrawState *st);

    /* The fog colour, 0x00RRGGBB (FirstDevice's DeviceInfo+0x14; the 3Dfx plugin passes it to grFogColorValue). */
    void (*set_fog_color)(uint32_t rgb);

    /* Mipmapping: 0 off (the base level only), 1 on, n >= 2 on with a sharper LOD bias of -(n-1)/2 (sparse detail such as the night stars is averaged away otherwise). */
    void (*set_mipmaps)(int on);

    /* Draw one convex polygon as a fan: v[0], v[i], v[i+1]. n is 3 or more (the game sends up to 9 or more).
     * `tex` may be NULL for an untextured polygon. */
    void (*draw_fan)(const HgVertex *v, uint32_t n, HgTex *tex, const HgDrawState *st);

    /* Clear the depth buffer only, leaving colour (SetState 0xc). The engine does this right after the sky and ground fills,
     * before the geometry. */
    void (*clear_depth)(void);

    /* Composite the 2D layer over the 3D picture. Called at most once per frame, before present(). */
    void (*draw_overlay)(const HgOverlay *o);

    /* Show the frame, then clear colour (black) and depth (far) for the next one. RefreshDisplay maps to this. */
    void (*present)(void);

    /* Save the frame drawn so far as a 24-bit BMP (for checking output without a screenshot). Optional, may be NULL.
     * Call before present(). Returns 0 on success. */
    int (*screenshot)(const char *path);

    /* Optional (may be NULL): add a point light over the geometry drawn so far. Returns 0 on success, non-zero if the backend cannot (the
     * plugin then draws the game's flat glow instead). */
    int (*draw_light)(const HgLight *l);
} HgBackend;

extern const HgBackend hg_backend_null;
extern const HgBackend hg_backend_d3d9;

#endif
