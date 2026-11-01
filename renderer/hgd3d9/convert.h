/* convert.h - pure conversions from the game's data to what a backend takes. No Windows or libc dependency,
 * so it builds freestanding for the plugin and natively for the unit tests (test/test_convert.c).
 *
 * The rules come from the 3Dfx plugin (FUN_10001f50 and neighbours in the decompilation) and from runtime logs;
 * see docs/research/renderer-interface.md. */
#ifndef HG_CONVERT_H
#define HG_CONVERT_H

#include <stdint.h>
#include "backend.h"

/* The game's vertex: 9 dwords, as passed to Render (offsets in docs/research/renderer-interface.md section 4). */
typedef struct GameVertex {
    float    x, y;      /*  0,  4  screen pixels */
    float    w;         /*  8      eye depth, 1 / (1/w); about FLT_MAX for the sky and ground fill. Not used: depth comes from oow */
    float    oow;       /* 12      1 / w, 0 at infinity */
    uint32_t light;     /* 16      an integer 0..255 (not a float: the dumps show 0x0000005f), multiplied into R, G, B */
    uint8_t  r, g, b, a;/* 20..23  colour and vertex alpha */
    uint32_t fog;       /* 24      top byte is an alpha / fog value */
    float    u, v;      /* 28, 32  0..1 */
} GameVertex;

/* How the plugin treats a draw: the blend flag selects where alpha comes from. */
typedef struct ConvertCtx {
    int      blend;     /* non-zero: alpha is the vertex alpha byte; zero: opaque */
    float    far_w;     /* depth limit for z = w / far_w (DeviceInfo+0x1c, 500000.0 seen); <= 0 uses the default */
    int      textured;  /* non-zero: texture coordinates are used */
    int      lit;       /* non-zero: vertex colour is the lit RGB; zero: white (the texture colour is used as is) */
    int      alpha_from_fog; /* non-zero (the fill primitives 14 to 17): alpha is 255 minus the fog byte, whatever the vertex alpha byte says */
    float    u_scale;   /* per-texture aspect scale for non-square textures (1, 0.5, 0.25, 0.125); 0 means 1 */
    float    v_scale;
    int      wquant;    /* non-zero: depth is quantised like the Voodoo's 16-bit floating W-buffer (12 significant bits), so distant polygons that are
                         * a few units apart tie, as they do natively, and the later one drawn wins */
    int      rhw_depth; /* non-zero: z = 1 - 1/w instead of w/far: linear in screen space like 1/w, so the interpolation across a large polygon is exact */
} ConvertCtx;

#define HG_DEFAULT_FAR_W 500000.0f

/* Convert one game vertex. Light is applied as (channel * light) >> 8, like the 3Dfx plugin.
 * z = (1 / oow) / far_w clamped to 0..1 (the W-buffer value; oow 0 is infinity), so the sky and ground fill land on the far plane.
 * u, v become 255 * c * scale / 256: the v1.2 3Dfx plugin computes Glide s = u * scale * oow * 255 (FUN_10002090 in the
 * 1.2 decompilation), with scale 1 for the square textures seen. The disc (1.0) build added half a texel; 1.2 does not. */
void hg_convert_vertex(HgVertex *out, const GameVertex *in, const ConvertCtx *ctx);

/* Palette to ARGB. `pal` has entries 0x00RRGGBB; the top byte is transparency (0xFF = transparent).
 * With `alpha_from_palette` (the 3Dfx plugin's alpha-palette textures, desc[6] == 1) alpha = 255 - top byte, else 255.
 * `key_rgb` >= 0 makes every entry with that RGB fully transparent (the chroma key); pass -1 for none.
 * `n` entries are read (the palette may be shorter than 256); indices past n read as entry 0. */
void hg_palette_to_argb(uint32_t out[256], const uint32_t *pal, uint32_t n, int alpha_from_palette, int64_t key_rgb);

/* Expand w*h 8-bit indices to 0xAARRGGBB through a palette made by hg_palette_to_argb. */
void hg_expand_indices(uint32_t *out, const uint8_t *idx, uint32_t w, uint32_t h, const uint32_t argb_pal[256]);

/* Clip a convex polygon (a triangle fan, n vertices of HgVertex) to the 640x480 view with a generous margin, because a pre-transformed
 * vertex far off screen (the engine sends ground polygons with coordinates around 20000) is not rasterised reliably by D3D9: part of
 * the polygon goes missing. A polygon already close to the view is copied unchanged. Returns the new vertex count (at most
 * HG_CLIP_IN + 4, written to `out`, which must hold HG_CLIP_MAX), or 0 if nothing is left. */
#define HG_CLIP_IN  24
#define HG_CLIP_MAX (HG_CLIP_IN + 8)
uint32_t hg_clip_fan(HgVertex *out, const HgVertex *in, uint32_t n);

/* The same, to an exact rectangle: the 3Dfx plugin clips every polygon to the view before drawing, so the outline of a clipped polygon has an
 * edge along the border of the view (native low-light frames show it). */
uint32_t hg_clip_rect(HgVertex *out, const HgVertex *in, uint32_t n, float x0, float y0, float x1, float y1);

#endif
