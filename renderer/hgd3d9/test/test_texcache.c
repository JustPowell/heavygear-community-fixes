/* Native tests for texcache.c with a mock backend. The fake Texture blocks live in the low 4 GB (MAP_32BIT) so that
 * their pointers fit the game's 32-bit words. */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "../texcache.h"

static int failures, checks;
#define CHECK(cond) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); } } while (0)

/* host functions the plugin normally provides */
void hg_log(const char *s) { (void)s; }
void hg_log_hex(uint32_t v) { (void)v; }
void hg_log_dec(uint32_t v) { (void)v; }
int hg_readable(const void *p, uint32_t n) { (void)n; return (uintptr_t)p > 0x10000 && (uintptr_t)p != 0xdead0000u; }

/* mock backend */
static int creates, updates, destroys, last_w, last_h;
static uint32_t last_argb[256 * 256];
static char handles[4096];
static int next_handle;
static uint32_t last_flags;
static HgTex *m_create(uint32_t w, uint32_t h, const uint32_t *argb, uint32_t flags) { last_flags = flags; creates++; last_w = (int)w; last_h = (int)h; memcpy(last_argb, argb, w * h * 4); return (HgTex *)&handles[next_handle++]; }
static int m_update(HgTex *t, uint32_t w, uint32_t h, const uint32_t *argb) { (void)t; updates++; last_w = (int)w; last_h = (int)h; memcpy(last_argb, argb, w * h * 4); return 0; }
static void m_destroy(HgTex *t) { (void)t; destroys++; }
static HgBackend mock;

static uint8_t *arena; static size_t arena_used;
static void *lowalloc(size_t n) { void *p = arena + arena_used; arena_used += (n + 63) & ~(size_t)63; return p; }

/* build a block + descriptor + (palette then pixels) for a w x h texture with `npal` palette entries */
typedef struct Tex { uint32_t *block; uint32_t *desc; uint32_t *pal; uint8_t *pix; } Tex;
static Tex make(uint32_t w, uint32_t h, uint32_t npal)
{
    Tex t;
    t.block = lowalloc(64); t.desc = lowalloc(32);
    t.pal = lowalloc(npal * 4 + w * h);              /* pixels directly after the palette */
    t.pix = (uint8_t *)(t.pal + npal);
    t.desc[0] = w; t.desc[1] = h; t.desc[2] = (uint32_t)(uintptr_t)t.pix; t.desc[3] = (uint32_t)(uintptr_t)t.pal;
    t.block[0] = (uint32_t)(uintptr_t)t.desc;
    return t;
}

int main(void)
{
    Tex a, b;
    HgTex *x, *y;
    uint32_t i;
    arena = mmap(0, 1 << 22, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    if (arena == MAP_FAILED) { printf("mmap failed\n"); return 2; }
    mock.tex_create = m_create; mock.tex_update = m_update; mock.tex_destroy = m_destroy;

    /* a 4x4 texture, 3 palette entries: opaque red, transparent green (top byte 0xFF), half-transparent blue */
    a = make(4, 4, 3);
    a.desc[6] = 1;                                 /* an alpha-palette texture */
    a.pal[0] = 0x00ff0000u; a.pal[1] = 0xff00ff00u; a.pal[2] = 0x800000ffu;
    for (i = 0; i < 16; i++) a.pix[i] = (uint8_t)(i % 3);
    x = hg_texcache_get(&mock, a.block, 1, 0);
    CHECK(x != 0 && creates == 1 && last_w == 4 && last_h == 4);
    CHECK(last_argb[0] == 0xffff0000u);          /* index 0: top byte 0 -> alpha 255 */
    CHECK((last_argb[1] >> 24) == 0);            /* index 1: 0xFF -> alpha 0 (its colour is bled from the neighbours) */
    CHECK((last_argb[2] >> 24) == 0x7f);           /* index 2: 0x80 -> alpha 127 (colour bled from the solid neighbours) */
    CHECK(hg_texcache_get(&mock, a.block, 2, 0) == x && creates == 1 && updates == 0);   /* cached */

    a.pal[0] = 0x0000ff00u;                       /* the palette changes in place */
    CHECK(hg_texcache_get(&mock, a.block, 3, 0) == x && updates == 1 && last_argb[0] == 0xff00ff00u);
    a.pix[5] = 0;                                 /* a pixel changes in place (it was 2) */
    CHECK(hg_texcache_get(&mock, a.block, 4, 0) == x && updates == 2);
    CHECK(hg_texcache_get(&mock, a.block, 5, 0) == x && updates == 2 && creates == 1);    /* unchanged again */

    /* not an alpha-palette texture: the top byte is ignored when unkeyed; a keyed draw takes alpha from the top byte (the particle
     * fix's rule) and makes the key colour transparent */
    { Tex c = make(2, 2, 4); HgTex *k;
      c.pal[0] = 0x00112233u; c.pal[1] = 0xff445566u; c.pal[2] = 0x00778899u; c.pal[3] = 0x00112233u;   /* entries 0 and 3 share RGB */
      c.pix[0] = 0; c.pix[1] = 1; c.pix[2] = 2; c.pix[3] = 3;
      c.desc[4] = 0;                               /* key index (garbage on unkeyed textures; here 0) */
      k = hg_texcache_get(&mock, c.block, 11, 0);
      CHECK(k != 0 && last_argb[0] == 0xff112233u && last_argb[1] == 0xff445566u);   /* opaque, no key */
      c.desc[4] = 0;
      CHECK(hg_texcache_get(&mock, c.block, 12, 1) == k);
      CHECK((last_argb[0] >> 24) == 0 && (last_argb[3] >> 24) == 0 && last_argb[2] == 0xff778899u);  /* both entries with the key's RGB */
      CHECK((last_argb[1] >> 24) == 0);           /* keyed: the top byte 0xFF now means transparent */
      c.desc[4] = 0x7baeb044u;                     /* an out-of-range key index is ignored */
      hg_texcache_get(&mock, c.block, 13, 1);
      CHECK(last_argb[0] == 0xff112233u && (last_argb[1] >> 24) == 0); }   /* no key colour, but alpha still from the palette */

    /* a palette of 10 entries (pixels start 40 bytes after it): indices past it read entry 0 */
    b = make(2, 2, 10);
    for (i = 0; i < 10; i++) b.pal[i] = 0x00000100u * (i + 1);
    b.pix[0] = 9; b.pix[1] = 200; b.pix[2] = 0; b.pix[3] = 1;
    y = hg_texcache_get(&mock, b.block, 6, 0);
    CHECK(y != 0 && y != x && creates == 3);
    CHECK(last_argb[0] == 0xff000a00u && last_argb[1] == 0xff000100u && last_argb[3] == 0xff000200u);

    /* the same address now holds a texture of another size */
    b.desc[0] = 4; b.desc[1] = 2;
    CHECK(hg_texcache_get(&mock, b.block, 7, 0) == (HgTex *)&handles[next_handle - 1] && destroys == 1 && creates == 4 && last_w == 4 && last_h == 2);

    /* bad input */
    { uint32_t bad[8] = {0}; bad[0] = 0xdead0000u; CHECK(hg_texcache_get(&mock, bad, 8, 0) == 0); }
    b.desc[0] = 0; CHECK(hg_texcache_get(&mock, b.block, 9, 0) == 0);          /* no size bit */
    b.desc[0] = 1u << 9; CHECK(hg_texcache_get(&mock, b.block, 9, 0) == 0);    /* larger than 256 */

    /* many textures: the cache clears itself instead of overflowing */
    { int before = destroys; uint32_t n;
      for (n = 0; n < 900; n++) { Tex t = make(1, 1, 2); t.pal[0] = n; t.pal[1] = n; t.pix[0] = 0; CHECK(hg_texcache_get(&mock, t.block, 10, 0) != 0); }
      CHECK(destroys > before && hg_texcache_count() < 800); }
    hg_texcache_clear(&mock);
    CHECK(hg_texcache_count() == 0);

    /* a sparse 256x256 texture (98% one index) gets no mip levels; a busy one does */
    a = make(256, 256, 4);
    for (i = 0; i < 4; i++) a.pal[i] = 0x00101010u * (i + 1);
    for (i = 0; i < 256 * 256; i++) a.pix[i] = (uint8_t)((i % 50) == 0 ? 1 + (i / 50) % 3 : 0);
    x = hg_texcache_get(&mock, a.block, 1, 0);
    CHECK(x != 0 && last_flags == HG_TEX_NO_MIPS);
    b = make(256, 256, 4);
    for (i = 0; i < 4; i++) b.pal[i] = 0x00101010u * (i + 1);
    for (i = 0; i < 256 * 256; i++) b.pix[i] = (uint8_t)(i % 4);
    y = hg_texcache_get(&mock, b.block, 1, 0);
    CHECK(y != 0 && last_flags == 0);
    /* a transparent texel takes the colour of its visible neighbours, keeping its alpha */
    { Tex c = make(2, 1, 2); c.desc[6] = 1; c.pal[0] = 0x00102030u; c.pal[1] = 0xff000000u; c.pix[0] = 0; c.pix[1] = 1;
      hg_texcache_get(&mock, c.block, 20, 0);
      CHECK(last_argb[1] == 0x00102030u); }
    printf("%d checks, %d failures\n", checks, failures);
    return failures != 0;
}
