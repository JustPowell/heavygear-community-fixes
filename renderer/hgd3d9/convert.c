#include "convert.h"

/* The 3Dfx plugin adds 786432.0 (3 * 2^18) to x and y before calling Glide. At that magnitude a float has 4 fractional bits, so the sum is the
 * coordinate rounded to 1/16 of a pixel, and the hardware draws the snapped polygon. Slivers thinner than that collapse to nothing, which a
 * rasteriser with finer sub-pixel precision would draw as a one-pixel line. Same rounding, same result. */
static float snap16(float v) { volatile float t = v + 786432.0f; return t - 786432.0f; }

/* Keep 12 significant bits of a positive float (a 4-bit exponent and 12-bit mantissa depth value has about this relative precision). */
static float quant12(float w)
{
    union { float f; uint32_t u; } v;
    v.f = w; v.u &= 0xfffff000u;           /* the float's 23-bit mantissa, top 11 bits kept */
    return v.f;
}

static uint32_t light_channel(uint8_t c, uint32_t light) { return ((uint32_t)c * light) >> 8; }

void hg_convert_vertex(HgVertex *out, const GameVertex *in, const ConvertCtx *ctx)
{
    uint32_t light = in->light;
    float far_w = ctx->far_w > 0.0f ? ctx->far_w : HG_DEFAULT_FAR_W;
    /* Depth from 1/w, the word the 3Dfx hardware's W-buffer uses (grDepthBufferMode(2)); word 2 (w) can be stale. oow 0 is infinity. */
    float z = in->oow > 0.0f ? (ctx->wquant ? quant12(1.0f / in->oow) : (1.0f / in->oow)) / far_w : 1.0f;
    /* The 3Dfx plugin's fill routine (FUN_10001e50 in 1.2) always uses 255 - fog byte as the alpha; its textured routine uses the vertex
     * alpha byte only when blending. */
    uint32_t a = ctx->alpha_from_fog ? 255u - (in->fog >> 24) : (ctx->blend ? in->a : 255u);

    if (ctx->rhw_depth) z = in->oow > 0.0f ? 1.0f - (in->oow < 1.0f ? in->oow : 1.0f) : 1.0f;
    if (light > 255) light = 255;
    if (!(z >= 0.0f)) z = 0.0f;               /* also catches NaN */
    if (z > 1.0f) z = 1.0f;

    out->x = snap16(in->x);
    out->y = snap16(in->y);
    out->z = z;
    out->rhw = in->oow;
    out->specular = in->fog & 0xff000000u;                 /* fog factor for D3D9's pre-transformed vertex fog: 0xFF = no fog */
    out->color = !ctx->lit ? 0xffffffffu : (a << 24) | (light_channel(in->r, light) << 16) | (light_channel(in->g, light) << 8) | light_channel(in->b, light);
    if (ctx->textured) {
        float us = ctx->u_scale > 0.0f ? ctx->u_scale : 1.0f, vs = ctx->v_scale > 0.0f ? ctx->v_scale : 1.0f;
        out->u = in->u * us * 255.0f / 256.0f;
        out->v = in->v * vs * 255.0f / 256.0f;
    } else {
        out->u = 0.0f;
        out->v = 0.0f;
    }
}

void hg_palette_to_argb(uint32_t out[256], const uint32_t *pal, uint32_t n, int alpha_from_palette, int64_t key_rgb)
{
    uint32_t i, e, a;
    if (n > 256) n = 256;
    for (i = 0; i < 256; i++) {
        e = i < n ? pal[i] : (n ? pal[0] : 0u);
        a = alpha_from_palette ? 255u - (e >> 24) : 255u;
        if (key_rgb >= 0 && (int64_t)(e & 0x00ffffffu) == key_rgb) a = 0;
        out[i] = (a << 24) | (e & 0x00ffffffu);
    }
}

void hg_expand_indices(uint32_t *out, const uint8_t *idx, uint32_t w, uint32_t h, const uint32_t argb_pal[256])
{
    uint32_t i, n = w * h;
    for (i = 0; i < n; i++) out[i] = argb_pal[idx[i]];
}

/* ---- clipping ------------------------------------------------------------------------------------------------------------------ */
static uint32_t lerp_argb(uint32_t a, uint32_t b, float t)
{
    uint32_t i, r = 0;
    for (i = 0; i < 32; i += 8) {
        float ca = (float)((a >> i) & 255u), cb = (float)((b >> i) & 255u), c = ca + (cb - ca) * t + 0.5f;
        if (c < 0.0f) c = 0.0f; if (c > 255.0f) c = 255.0f;
        r |= (uint32_t)c << i;
    }
    return r;
}

/* The point on edge a-b at parameter t (along the screen-space edge). Depth, 1/w, colour and fog vary linearly in screen space; the
 * texture coordinates are perspective-correct, so u/w and v/w are what varies linearly. */
static void lerp_vertex(HgVertex *o, const HgVertex *a, const HgVertex *b, float t)
{
    o->x = a->x + (b->x - a->x) * t;
    o->y = a->y + (b->y - a->y) * t;
    o->z = a->z + (b->z - a->z) * t;
    o->rhw = a->rhw + (b->rhw - a->rhw) * t;
    o->color = lerp_argb(a->color, b->color, t);
    o->specular = lerp_argb(a->specular, b->specular, t);
    if (a->rhw > 0.0f && b->rhw > 0.0f && o->rhw > 0.0f) {
        float ua = a->u * a->rhw, ub = b->u * b->rhw, va = a->v * a->rhw, vb = b->v * b->rhw;
        o->u = (ua + (ub - ua) * t) / o->rhw;
        o->v = (va + (vb - va) * t) / o->rhw;
    } else {
        o->u = a->u + (b->u - a->u) * t;
        o->v = a->v + (b->v - a->v) * t;
    }
}

static uint32_t clip_plane(HgVertex *out, const HgVertex *in, uint32_t n, int axis, float limit, int keep_greater)
{
    uint32_t i, m = 0;
    for (i = 0; i < n; i++) {
        const HgVertex *p = &in[i], *q = &in[(i + 1) % n];
        float dp = (axis ? p->y : p->x) - limit, dq = (axis ? q->y : q->x) - limit;
        int pin, qin;
        if (!keep_greater) { dp = -dp; dq = -dq; }
        pin = dp >= 0.0f; qin = dq >= 0.0f;
        if (pin) out[m++] = *p;
        if (pin != qin) lerp_vertex(&out[m++], p, q, dp / (dp - dq));
    }
    return m;
}

uint32_t hg_clip_rect(HgVertex *out, const HgVertex *in, uint32_t n, float x0, float y0, float x1, float y1)
{
    HgVertex a[HG_CLIP_MAX], b[HG_CLIP_MAX];
    uint32_t i, m;
    int inside = 1;
    if (n > HG_CLIP_IN) n = HG_CLIP_IN;
    for (i = 0; i < n; i++)
        if (!(in[i].x >= x0 && in[i].x <= x1 && in[i].y >= y0 && in[i].y <= y1)) inside = 0;
    if (inside) { for (i = 0; i < n; i++) out[i] = in[i]; return n; }
    for (i = 0; i < n; i++) a[i] = in[i];
    m = clip_plane(b, a, n, 0, x0, 1); if (m < 3) return 0;
    m = clip_plane(a, b, m, 0, x1, 0); if (m < 3) return 0;
    m = clip_plane(b, a, m, 1, y0, 1); if (m < 3) return 0;
    m = clip_plane(a, b, m, 1, y1, 0); if (m < 3) return 0;
    for (i = 0; i < m; i++) out[i] = a[i];
    return m;
}

uint32_t hg_clip_fan(HgVertex *out, const HgVertex *in, uint32_t n)
{
    const float lo_x = -256.0f, hi_x = 896.0f, lo_y = -256.0f, hi_y = 736.0f;      /* inside this, leave the polygon alone */
    uint32_t i;
    int inside = 1;
    if (n > HG_CLIP_IN) n = HG_CLIP_IN;
    for (i = 0; i < n; i++)
        if (!(in[i].x >= lo_x && in[i].x <= hi_x && in[i].y >= lo_y && in[i].y <= hi_y)) inside = 0;
    if (inside) { for (i = 0; i < n; i++) out[i] = in[i]; return n; }
    return hg_clip_rect(out, in, n, -16.0f, -16.0f, 656.0f, 496.0f);               /* otherwise clip to a rectangle well outside the 640x480 view */
}
