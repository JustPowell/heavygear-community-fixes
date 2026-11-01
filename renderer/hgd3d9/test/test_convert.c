/* Native unit tests for convert.c. Run with test/run.sh. Expected values are worked out by hand from the rules in
 * convert.h (which come from the 3Dfx plugin's FUN_10001f50 and docs/research/renderer-interface.md). */
#include <stdio.h>
#include <float.h>
#include "../convert.h"

static int failures, checks;
#define CHECK(cond) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)
static int near_f(float a, float b) { float d = a - b; if (d < 0) d = -d; return d < 1e-5f; }

static GameVertex gv(uint32_t light, uint8_t r, uint8_t g, uint8_t b, uint8_t a)
{
    GameVertex v = { 100.0f, 50.0f, 78000.0f, 1.0f / 78000.0f, light, r, g, b, a, 0, 0.5f, 0.25f };
    return v;
}

static void test_light(void)
{
    HgVertex o; ConvertCtx c = { 0, 0.0f, 0, 1, 0, 0.0f, 0.0f, 0 }; GameVertex v;
    v = gv(255, 255, 255, 255, 255); hg_convert_vertex(&o, &v, &c);
    CHECK((o.color & 0x00ffffff) == 0x00fefefe);          /* 255 * 255 >> 8 = 254 */
    v = gv(0, 200, 100, 50, 255); hg_convert_vertex(&o, &v, &c);
    CHECK((o.color & 0x00ffffff) == 0);                   /* no light, black */
    v = gv(128, 200, 100, 50, 255); hg_convert_vertex(&o, &v, &c);
    CHECK(o.color == 0xff643219u);                        /* 100, 50, 25 */
    v = gv(95, 255, 0, 0, 255); hg_convert_vertex(&o, &v, &c);
    CHECK(((o.color >> 16) & 255) == ((255u * 95u) >> 8));
    v = gv(0x5f, 254, 254, 254, 255); hg_convert_vertex(&o, &v, &c);
    CHECK((o.color & 255) == ((254u * 0x5fu) >> 8));      /* the real value seen in a dump: word 4 = 0x0000005f */
    v = gv(999, 255, 255, 255, 255); hg_convert_vertex(&o, &v, &c);
    CHECK((o.color & 255) == 254);                         /* clamped to 255 */
    v = gv(0xffffffffu, 255, 255, 255, 255); hg_convert_vertex(&o, &v, &c);
    CHECK((o.color & 255) == 254);                         /* a stray high value cannot overflow the channel */
}

static void test_unlit(void)
{
    HgVertex o; GameVertex v = gv(95, 200, 100, 50, 0x40);
    ConvertCtx c = { 1, 0.0f, 1, 0, 0, 0.0f, 0.0f, 0 };
    hg_convert_vertex(&o, &v, &c);
    CHECK(o.color == 0xffffffffu);                          /* unlit: the texture colour is used as is, vertex alpha ignored */
}

static void test_fog_and_fill_alpha(void)
{
    HgVertex o; GameVertex v = gv(255, 10, 20, 30, 0x40);
    ConvertCtx fill = { 1, 0.0f, 0, 1, 1, 0.0f, 0.0f, 0 };      /* a blended fill: alpha comes from the fog byte */
    v.fog = 0xff000000u; hg_convert_vertex(&o, &v, &fill);
    CHECK((o.color >> 24) == 0x00);                          /* fog byte 0xFF -> alpha 0: the glow polygons are invisible */
    CHECK((o.specular >> 24) == 0xff);                       /* and no fog */
    v.fog = 0x7c000000u; hg_convert_vertex(&o, &v, &fill);
    CHECK((o.color >> 24) == 255u - 0x7c);                   /* fog byte 0x7c -> alpha 131 */
    CHECK((o.specular >> 24) == 0x7c && (o.specular & 0x00ffffffu) == 0);
    v.fog = 0x00000000u; hg_convert_vertex(&o, &v, &fill);
    CHECK((o.color >> 24) == 255 && (o.specular >> 24) == 0);   /* fog byte 0: fully fogged, alpha 255 */
}

static void test_wquant(void)
{
    HgVertex a, b; ConvertCtx c = { 0, 0.0f, 0, 1, 0, 0.0f, 0.0f, 1 }; GameVertex v = gv(255, 1, 1, 1, 255), u;
    v.oow = 1.0f / 78000.0f; u = v; u.oow = 1.0f / 78010.0f;      /* 10 units apart at 78000 (resolution there is 32) */
    hg_convert_vertex(&a, &v, &c); hg_convert_vertex(&b, &u, &c);
    CHECK(a.z == b.z);                                               /* tie, like the 16-bit W-buffer */
    c.wquant = 0; hg_convert_vertex(&a, &v, &c); hg_convert_vertex(&b, &u, &c);
    CHECK(a.z != b.z);                                               /* distinct without it */
    c.wquant = 1; v.oow = 1.0f / 200.0f; u.oow = 1.0f / 205.0f; hg_convert_vertex(&a, &v, &c); hg_convert_vertex(&b, &u, &c);
    CHECK(a.z != b.z);                                               /* near the camera the resolution is much finer */
}

static void test_snap(void)
{
    HgVertex o; ConvertCtx c = { 0, 0.0f, 0, 1, 0, 0.0f, 0.0f, 0 }; GameVertex v = gv(255, 1, 1, 1, 255);
    v.x = 100.03f; v.y = 49.97f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.x == 100.0f && o.y == 50.0f);                    /* rounds to the nearest 1/16 */
    v.x = 100.04f; v.y = 0.5f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.x == 100.0625f && o.y == 0.5f);                  /* 100.04 is nearer 100.0625 than 100.0 */
    v.x = -3.2f; v.y = 479.99f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.x == -3.1875f && o.y == 480.0f);                 /* negatives and the far edge */
    v.x = 200.0f; v.y = 300.0f; hg_convert_vertex(&o, &v, &c);
    { HgVertex a, b; GameVertex u = v; u.x = 200.0f; u.y = 300.02f; hg_convert_vertex(&a, &v, &c); hg_convert_vertex(&b, &u, &c);
      CHECK(a.y == b.y); }                                   /* a 0.02 pixel sliver collapses: the same row after snapping */
}

static void test_alpha(void)
{
    HgVertex o; GameVertex v = gv(255, 10, 20, 30, 0x40);
    ConvertCtx opaque = { 0, 0.0f, 0, 1, 0, 0.0f, 0.0f, 0 }, blend = { 1, 0.0f, 0, 1, 0, 0.0f, 0.0f, 0 };
    hg_convert_vertex(&o, &v, &opaque); CHECK((o.color >> 24) == 0xff);
    hg_convert_vertex(&o, &v, &blend);  CHECK((o.color >> 24) == 0x40);
}

static void test_depth(void)
{
    HgVertex o; ConvertCtx c = { 0, 0.0f, 0, 1, 0, 0.0f, 0.0f, 0 }; GameVertex v = gv(255, 1, 1, 1, 255);
    hg_convert_vertex(&o, &v, &c); CHECK(near_f(o.z, 78000.0f / HG_DEFAULT_FAR_W));      /* from oow = 1/78000 */
    CHECK(near_f(o.rhw, 1.0f / 78000.0f));
    v.w = 5.0f; hg_convert_vertex(&o, &v, &c); CHECK(near_f(o.z, 78000.0f / HG_DEFAULT_FAR_W));   /* a stale w is ignored */
    v.w = FLT_MAX; v.oow = 0.0f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.z == 1.0f); CHECK(o.rhw == 0.0f);               /* infinity: the sky fill sits on the far plane */
    v.oow = -1.0f; hg_convert_vertex(&o, &v, &c); CHECK(o.z == 1.0f);       /* a bad value cannot reach the near plane */
    v.oow = 0.0f / 0.0f; hg_convert_vertex(&o, &v, &c); CHECK(o.z == 1.0f);  /* NaN */
    v.oow = 1.0f / 1000.0f; c.far_w = 2000.0f; hg_convert_vertex(&o, &v, &c); CHECK(near_f(o.z, 0.5f));
    v.oow = 1.0f / 750000.0f; c.far_w = 0.0f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.z == 1.0f);                                     /* just past the far limit clamps to exactly 1 */
    v.oow = 1.0f / 78000.0f;
    CHECK(o.x == 100.0f && o.y == 50.0f);                   /* whole numbers are unchanged by the 1/16 snap */
}

static void test_uv(void)
{
    HgVertex o; GameVertex v = gv(255, 1, 1, 1, 255);
    ConvertCtx c = { 0, 0.0f, 1, 1, 0, 0.0f, 0.0f, 0 };
    v.u = 0.0f; v.v = 1.0f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.u == 0.0f);                                     /* v1.2: no half-texel offset */
    CHECK(near_f(o.v, 255.0f / 256.0f));                    /* Glide s = 255u, in 0..1 that is 255/256 */
    v.u = 0.5f; hg_convert_vertex(&o, &v, &c);
    CHECK(near_f(o.u, 0.5f * 255.0f / 256.0f));
    c.u_scale = 0.5f; c.v_scale = 0.25f; v.u = 1.0f; v.v = 1.0f; hg_convert_vertex(&o, &v, &c);
    CHECK(near_f(o.u, 0.5f * 255.0f / 256.0f));             /* aspect scales for non-square textures */
    CHECK(near_f(o.v, 0.25f * 255.0f / 256.0f));
    c.textured = 0; v.u = 0.7f; hg_convert_vertex(&o, &v, &c);
    CHECK(o.u == 0.0f && o.v == 0.0f);                      /* untextured polygons carry no coordinates */
}

static void test_palette(void)
{
    uint32_t pal[4] = { 0x00112233u, 0xff445566u, 0x40778899u, 0x0000ff00u }, out[256];
    hg_palette_to_argb(out, pal, 4, 1, -1);
    CHECK(out[0] == 0xff112233u);        /* alpha palette: top byte 0 = opaque */
    CHECK(out[1] == 0x00445566u);        /* top byte 0xFF = transparent */
    CHECK(out[2] == 0xbf778899u);        /* 255 - 0x40 */
    CHECK(out[3] == 0xff00ff00u);
    CHECK(out[200] == out[0]);           /* indices past the palette read entry 0 */
    hg_palette_to_argb(out, pal, 4, 0, -1);
    CHECK(out[1] == 0xff445566u && out[2] == 0xff778899u);   /* not an alpha palette: always opaque */
    hg_palette_to_argb(out, pal, 4, 1, 0x00112233);
    CHECK(out[0] == 0x00112233u && out[3] == 0xff00ff00u);   /* the chroma key makes that colour transparent */
    hg_palette_to_argb(out, pal, 4, 0, 0x000000ff00);
    CHECK(out[3] == 0xff00ff00u || out[3] == 0x0000ff00u);
    hg_palette_to_argb(out, pal, 0, 1, -1);
    CHECK(out[5] == 0xff000000u);        /* an empty palette gives opaque black, not garbage */
}

static void test_expand(void)
{
    uint32_t pal[256], argb[256], tex[4];
    uint8_t idx[4] = { 0, 1, 1, 0 };
    int i;
    for (i = 0; i < 256; i++) pal[i] = (uint32_t)i;                 /* top byte 0, so alpha 255 */
    hg_palette_to_argb(argb, pal, 256, 1, -1);
    hg_expand_indices(tex, idx, 2, 2, argb);
    CHECK(tex[0] == 0xff000000u && tex[1] == 0xff000001u && tex[2] == 0xff000001u && tex[3] == 0xff000000u);
}

static void test_clip(void)
{
    HgVertex in[4], out[HG_CLIP_MAX]; uint32_t n, i; int ok;
    /* a polygon well inside is untouched */
    for (i = 0; i < 4; i++) { in[i].x = i == 1 || i == 2 ? 600.0f : 40.0f; in[i].y = i >= 2 ? 400.0f : 30.0f; in[i].z = 0.5f; in[i].rhw = 0.01f; in[i].color = 0xff808080u; in[i].specular = 0xff000000u; in[i].u = (float)(i & 1); in[i].v = (float)(i >> 1); }
    n = hg_clip_fan(out, in, 4); CHECK(n == 4 && out[2].x == in[2].x);
    /* the game's ground polygon: corners at +-20000 */
    in[0].x = -23151.0f; in[0].y = 2625.0f; in[1].x = 18901.0f; in[1].y = 2625.0f; in[2].x = 1198.0f; in[2].y = 346.0f; in[3].x = -172.0f; in[3].y = 321.0f;
    in[0].rhw = in[1].rhw = 0.00621f; in[2].rhw = 0.000239f; in[3].rhw = 0.000174f;
    n = hg_clip_fan(out, in, 4);
    CHECK(n >= 3 && n <= 8);
    ok = 1; for (i = 0; i < n; i++) if (!(out[i].x >= -16.01f && out[i].x <= 656.01f && out[i].y >= -16.01f && out[i].y <= 496.01f)) ok = 0;
    CHECK(ok);
    ok = 1; for (i = 0; i < n; i++) if (!(out[i].rhw > 0.000174f - 1e-7f && out[i].rhw < 0.00621f + 1e-7f)) ok = 0;
    CHECK(ok);                                             /* interpolated 1/w stays between the corner values */
    /* a polygon entirely off to the left disappears */
    for (i = 0; i < 4; i++) { in[i].x = -900.0f - (float)i; in[i].y = (float)(i * 50); }
    n = hg_clip_fan(out, in, 4); CHECK(n == 0);
    /* a polygon straddling the right edge keeps its inside corners and gets new ones on the clip line, with u interpolated */
    in[0].x = 300.0f; in[0].y = 100.0f; in[1].x = 1400.0f; in[1].y = 100.0f; in[2].x = 1400.0f; in[2].y = 300.0f; in[3].x = 300.0f; in[3].y = 300.0f;
    for (i = 0; i < 4; i++) in[i].rhw = 0.01f;
    in[0].u = in[3].u = 0.0f; in[1].u = in[2].u = 1.0f;
    n = hg_clip_fan(out, in, 4); CHECK(n == 4);
    ok = 0; for (i = 0; i < n; i++) if (near_f(out[i].x, 656.0f) && out[i].u > 0.32f && out[i].u < 0.33f) ok = 1;   /* (656-300)/1100 = 0.3236 */
    CHECK(ok);
}

int main(void)
{
    test_light(); test_unlit(); test_fog_and_fill_alpha(); test_snap(); test_wquant(); test_alpha(); test_depth(); test_uv(); test_palette(); test_expand(); test_clip();
    printf("%d checks, %d failures\n", checks, failures);
    return failures != 0;
}
