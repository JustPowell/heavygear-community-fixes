#include "texcache.h"
#include "convert.h"

#define SLOTS 1024
#define MAX_LIVE (SLOTS * 3 / 4)     /* clear everything when this many are live: crude, but eviction is rare */

typedef struct Entry {
    uintptr_t key;                   /* pixel pointer (desc[2]); 0 = free */
    HgTex    *tex;
    uint32_t  w, h, npal, pal_hash, pix_hash, mode;   /* mode: bit 0 alpha palette, bit 1 keyed, bits 8.. key index */
} Entry;

static Entry    g_e[SLOTS];
static uint32_t g_live, g_creates, g_updates;
static int      g_black_key;                 /* keyed texture whose key index lies past the palette: key colour = black (the 3Dfx reads the entry past the end, which is 0) */
void hg_texcache_set_black_key(int on) { g_black_key = on; }
static uint32_t g_argb[256 * 256];   /* scratch for conversion */

static uint32_t highbit(uint32_t m)  /* index of the highest set bit, or 32 if none */
{
    int i;
    for (i = 31; i >= 0; i--) if (m & (1u << i)) return (uint32_t)i;
    return 32;
}

static int readable_u32(const uint32_t *p, uint32_t n) { return hg_readable(p, n * 4); }

static uint32_t fnv(uint32_t h, uint32_t v) { return (h ^ v) * 16777619u; }

static uint32_t hash_palette(const uint32_t *pal, uint32_t n)
{
    uint32_t i, h = 2166136261u;
    for (i = 0; i < n; i++) h = fnv(h, pal[i]);
    return h;
}

/* Sparse: about 1024 samples however large the texture. Catches animated textures without reading 64 KB per draw. */
static uint32_t hash_pixels(const uint8_t *p, uint32_t count)
{
    uint32_t i, step = count / 1024, h = 2166136261u;
    if (step == 0) step = 1;
    for (i = 0; i < count; i += step) h = fnv(h, p[i]);
    return fnv(h, p[count - 1]);
}

void hg_texcache_clear(const HgBackend *be)
{
    uint32_t i;
    for (i = 0; i < SLOTS; i++) {
        if (g_e[i].key && g_e[i].tex) be->tex_destroy(g_e[i].tex);
        g_e[i].key = 0; g_e[i].tex = 0;
    }
    g_live = 0;
}

uint32_t hg_texcache_count(void) { return g_live; }
void hg_texcache_stats(uint32_t *creates, uint32_t *updates) { *creates = g_creates; *updates = g_updates; }

/* For finding out what keyed (particle) textures look like after conversion: the first few are described in the log. */
static uint32_t g_described;
static void describe_keyed(uint32_t w, uint32_t h, uint32_t npal, uint32_t kidx, int64_t key_rgb, int alpha_pal,
                           const uint32_t *pal, const uint32_t *argb, uint32_t desc6)
{
    uint32_t i, n = w * h, a0 = 0, a255 = 0, apart = 0, top_nonzero = 0;
    if (g_described >= 40) return;
    g_described++;
    for (i = 0; i < n; i++) { uint32_t a = argb[i] >> 24; if (a == 0) a0++; else if (a == 255) a255++; else apart++; }
    for (i = 0; i < npal; i++) if (pal[i] >> 24) top_nonzero++;
    hg_log("keyed texture "); hg_log_dec(w); hg_log("x"); hg_log_dec(h); hg_log(": palette "); hg_log_dec(npal);
    hg_log(" entries ("); hg_log_dec(top_nonzero); hg_log(" with a top byte), key index "); hg_log_dec(kidx);
    hg_log(key_rgb >= 0 ? " used" : " ignored"); hg_log(", desc[6] "); hg_log_dec(desc6); hg_log(alpha_pal ? ", alpha from palette" : ", opaque");
    hg_log(". After conversion: transparent "); hg_log_dec(a0); hg_log(", partial "); hg_log_dec(apart); hg_log(", opaque "); hg_log_dec(a255);
    hg_log(" of "); hg_log_dec(n); hg_log(" texels\r\n");
}

/* Sparse textures (the night sky: a few bright pixels on one background colour) lose their detail in mip levels, so they get none. */
static uint32_t tex_flags(const uint8_t *pix, uint32_t n)
{
    uint32_t hist[256] = {0}, i, best = 0;
    if (n < 16384) return 0;
    for (i = 0; i < n; i++) hist[pix[i]]++;
    for (i = 0; i < 256; i++) if (hist[i] > best) best = hist[i];
    return best >= n / 10 * 9 ? HG_TEX_NO_MIPS : 0;
}

static int g_nobleed;
static uint32_t g_bleed_solid = 140, g_bleed_passes = 2;   /* texels below this alpha take the colour of those at or above it, over this many texel rings */
void hg_texcache_set_bleed_params(uint32_t solid, uint32_t passes) { g_bleed_solid = solid; g_bleed_passes = passes; }
void hg_texcache_set_bleed(int on) { g_nobleed = !on; }

/* Texels that are (nearly) transparent carry an arbitrary colour, usually black. Bilinear filtering and the mip chain mix it into the visible
 * texels' edge, and the blend then darkens the picture behind in a halo (the dark rim around the explosions). Give those texels the colour of
 * their visible neighbours instead; their own alpha is kept. The faint edge texels of the explosion sprites are dark red-brown, which showed as a
 * dark rim against a lit ground; they now carry the fireball's colour. */
static void bleed(uint32_t *t, uint32_t w, uint32_t h)
{
    static uint8_t known[256 * 256];
    uint32_t x, y, i, pass, any = 0;
    for (i = 0; i < w * h; i++) { known[i] = (t[i] >> 24) >= g_bleed_solid; any |= !known[i]; }
    if (!any) return;
    for (pass = 0; pass < g_bleed_passes; pass++) {
        static uint32_t nxt[256 * 256]; static uint8_t nk[256 * 256]; uint32_t changed = 0;
        for (i = 0; i < w * h; i++) { nxt[i] = t[i]; nk[i] = known[i]; }
        for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
            uint32_t sr = 0, sg = 0, sb = 0, sw = 0; int dx, dy;
            if (known[y * w + x]) continue;
            for (dy = -1; dy <= 1; dy++) for (dx = -1; dx <= 1; dx++) {
                int xx = (int)x + dx, yy = (int)y + dy; uint32_t c, a;
                if (xx < 0 || yy < 0 || xx >= (int)w || yy >= (int)h || !known[yy * w + xx]) continue;
                c = t[yy * w + xx]; a = (c >> 24) + 1;
                sr += ((c >> 16) & 255) * a; sg += ((c >> 8) & 255) * a; sb += (c & 255) * a; sw += a;
            }
            if (sw) { nxt[y * w + x] = (t[y * w + x] & 0xff000000u) | ((sr / sw) << 16) | ((sg / sw) << 8) | (sb / sw); nk[y * w + x] = 1; changed = 1; }
        }
        for (i = 0; i < w * h; i++) { t[i] = nxt[i]; known[i] = nk[i]; }
        if (!changed) break;
    }
}

static void convert(uint32_t *out, const uint8_t *pix, uint32_t w, uint32_t h, const uint32_t *pal, uint32_t npal,
                    int alpha_pal, int64_t key_rgb)
{
    uint32_t argb_pal[256];
    hg_palette_to_argb(argb_pal, pal, npal, alpha_pal, key_rgb);
    hg_expand_indices(out, pix, w, h, argb_pal);
    if (!g_nobleed) bleed(out, w, h);
}

int hg_tex_source(const uint32_t *block, HgTexSrc *s)
{
    const uint32_t *desc;
    uint32_t wb, hb;
    uintptr_t pixp, palp;

    desc = (const uint32_t *)(uintptr_t)block[0];
    if (!hg_readable(desc, 16)) return 1;
    wb = highbit(desc[0]); hb = highbit(desc[1]);
    if (wb > 8 || hb > 8) return 1;
    s->w = 1u << wb; s->h = 1u << hb;
    pixp = (uintptr_t)desc[2]; palp = (uintptr_t)desc[3];
    s->pix = (const uint8_t *)pixp; s->pal = (const uint32_t *)palp;

    s->npal = 256;
    if (pixp > palp && pixp - palp <= 1024 && ((pixp - palp) & 3) == 0) s->npal = (uint32_t)((pixp - palp) / 4);
    if (!hg_readable(s->pal, s->npal * 4) || !hg_readable(s->pix, s->w * s->h)) return 1;
    s->desc = desc;
    s->desc_raw[0] = desc[0]; s->desc_raw[1] = desc[1]; s->desc_raw[2] = desc[4];
    s->desc_raw[3] = readable_u32(desc, 7) ? desc[5] : 0;
    s->desc_raw[4] = readable_u32(desc, 7) ? desc[6] : 0;
    return 0;
}

HgTex *hg_texcache_get(const HgBackend *be, const uint32_t *block, uint32_t frame, int keyed)
{
    const uint32_t *desc;
    const uint8_t *pix;
    const uint32_t *pal;
    uint32_t w, h, npal, ph, xh, slot, probes, mode, kidx;
    int alpha_pal, usekey;
    int64_t key_rgb;
    uintptr_t pixp;
    Entry *e;
    HgTexSrc src;
    (void)frame;

    if (hg_tex_source(block, &src)) return (HgTex *)0;
    desc = src.desc; pix = src.pix; pal = src.pal; w = src.w; h = src.h; npal = src.npal;
    pixp = (uintptr_t)pix;

    /* Alpha from the palette's top byte for the alpha-palette textures (desc[6] == 1) and for every keyed texture: the particle
     * fix in tools/glidelog established that keyed particle textures keep their transparency there although the plugin does not
     * flag them. */
    alpha_pal = (readable_u32(desc, 7) && desc[6] == 1) || keyed;
    kidx = desc[4];
    usekey = keyed && kidx < npal;
    key_rgb = usekey ? (int64_t)(pal[kidx] & 0x00ffffffu) : -1;
    if (keyed && !usekey && g_black_key) key_rgb = 0;
    mode = (alpha_pal ? 1u : 0u) | (usekey ? 2u | (kidx << 8) : 0u) | (key_rgb == 0 && !usekey ? 4u : 0u);
    ph = hash_palette(pal, npal);
    xh = hash_pixels(pix, w * h);

    slot = (uint32_t)(pixp >> 4) & (SLOTS - 1);
    for (probes = 0; probes < SLOTS; probes++, slot = (slot + 1) & (SLOTS - 1)) {
        e = &g_e[slot];
        if (e->key == pixp) {
            if (e->w != w || e->h != h) {                 /* the address now holds a different texture */
                be->tex_destroy(e->tex);
                convert(g_argb, pix, w, h, pal, npal, alpha_pal, key_rgb);
                e->tex = be->tex_create(w, h, g_argb, tex_flags(pix, w * h));
                g_creates++;
                e->w = w; e->h = h;
            } else if (e->pal_hash != ph || e->npal != npal || e->pix_hash != xh || e->mode != mode) {
                convert(g_argb, pix, w, h, pal, npal, alpha_pal, key_rgb);
                be->tex_update(e->tex, w, h, g_argb);
                g_updates++;
            }
            e->npal = npal; e->pal_hash = ph; e->pix_hash = xh; e->mode = mode;
            return e->tex;
        }
        if (e->key == 0) break;
    }
    if (g_live >= MAX_LIVE) {
        hg_log("texture cache full, clearing\r\n");
        hg_texcache_clear(be);
        slot = (uint32_t)(pixp >> 4) & (SLOTS - 1);
    }
    while (g_e[slot].key) slot = (slot + 1) & (SLOTS - 1);
    e = &g_e[slot];
    convert(g_argb, pix, w, h, pal, npal, alpha_pal, key_rgb);
    if (keyed) describe_keyed(w, h, npal, kidx, key_rgb, alpha_pal, pal, g_argb, desc[6]);
    e->tex = be->tex_create(w, h, g_argb, tex_flags(pix, w * h));
    if (!e->tex) return (HgTex *)0;
    g_creates++;
    e->key = pixp; e->w = w; e->h = h; e->npal = npal; e->pal_hash = ph; e->pix_hash = xh; e->mode = mode;
    g_live++;
    return e->tex;
}
