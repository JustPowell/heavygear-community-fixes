/* capture.c - writes the capture file (capture.h). Freestanding. */
#define HG_CAP_RECORDER
#include <stddef.h>
#include "capture.h"
#include "backend.h"
#include "texcache.h"

void *memcpy(void *, const void *, size_t);   /* rt.c */

#define WINAPI __stdcall
__declspec(dllimport) void *WINAPI CreateFileA(const char *, uint32_t, uint32_t, void *, uint32_t, uint32_t, void *);
__declspec(dllimport) int WINAPI WriteFile(void *, const void *, uint32_t, uint32_t *, void *);
__declspec(dllimport) int WINAPI CloseHandle(void *);

#define BUF_BYTES (1u << 20)
#define MAX_BYTES (900u * 1024u * 1024u)     /* stop recording past this, so a forgotten control file cannot fill the disk */
#define TEXSLOTS 8192

static void    *g_f;
static uint8_t  g_buf[BUF_BYTES];
static uint32_t g_n, g_total, g_next_tex;
static uint16_t g_prev[HG_CAP_OVERLAY_WORDS];

typedef struct TexRec { uintptr_t pix; uint32_t ph, xh, w, h, npal, id; } TexRec;
static TexRec g_tex[TEXSLOTS];

static void flush(void)
{
    uint32_t w;
    if (g_f && g_n) WriteFile(g_f, g_buf, g_n, &w, 0);
    g_n = 0;
}
static void put_bytes(const void *p, uint32_t n)
{
    const uint8_t *s = (const uint8_t *)p;
    g_total += n;
    while (n) {
        uint32_t room = BUF_BYTES - g_n, c = n < room ? n : room;
        memcpy(g_buf + g_n, s, c);
        g_n += c; s += c; n -= c;
        if (g_n == BUF_BYTES) flush();
    }
}
static void put_u32(uint32_t v) { put_bytes(&v, 4); }
static void rec_head(uint32_t tag, uint32_t bytes) { put_u32(tag); put_u32(bytes); }

int hg_cap_active(void) { return g_f != 0 && g_total < MAX_BYTES; }

int hg_cap_open(const char *path)
{
    g_f = CreateFileA(path, 0x40000000, 0, 0, 2, 0x80, 0);
    if (g_f == (void *)-1) { g_f = 0; return 1; }
    put_bytes(HG_CAP_MAGIC, 8); put_u32(1); put_u32(0);
    return 0;
}

void hg_cap_init(const uint32_t *info, uint32_t n)
{
    if (!hg_cap_active()) return;
    rec_head(HG_CAP_INIT, 4 + n * 4); put_u32(n); put_bytes(info, n * 4);
}

static uint32_t fnv(uint32_t h, uint32_t v) { return (h ^ v) * 16777619u; }

/* The texture's id: a new TEXT record when this pixel address holds content not seen before (the same sparse hashes as the cache). */
static uint32_t texture_id(const uint32_t *block)
{
    HgTexSrc s;
    uint32_t i, ph = 2166136261u, xh = 2166136261u, n, step, slot, k;
    if (hg_tex_source(block, &s)) return HG_CAP_NOTEX;
    for (i = 0; i < s.npal; i++) ph = fnv(ph, s.pal[i]);
    n = s.w * s.h; step = n / 1024; if (!step) step = 1;
    for (i = 0; i < n; i += step) xh = fnv(xh, s.pix[i]);
    xh = fnv(xh, s.pix[n - 1]);
    slot = (uint32_t)(((uintptr_t)s.pix >> 4) ^ ph ^ (xh * 7u)) & (TEXSLOTS - 1);
    for (k = 0; k < TEXSLOTS; k++, slot = (slot + 1) & (TEXSLOTS - 1)) {
        TexRec *t = &g_tex[slot];
        if (!t->w) {                                        /* new */
            t->pix = (uintptr_t)s.pix; t->ph = ph; t->xh = xh; t->w = s.w; t->h = s.h; t->npal = s.npal; t->id = g_next_tex++;
            rec_head(HG_CAP_TEXT, 9 * 4 + s.npal * 4 + n);
            put_u32(t->id); put_u32(s.w); put_u32(s.h); put_u32(s.npal);
            for (i = 0; i < 5; i++) put_u32(s.desc_raw[i]);
            put_bytes(s.pal, s.npal * 4); put_bytes(s.pix, n);
            return t->id;
        }
        if (t->pix == (uintptr_t)s.pix && t->ph == ph && t->xh == xh && t->w == s.w && t->h == s.h && t->npal == s.npal) return t->id;
    }
    return HG_CAP_NOTEX;                                    /* table full */
}

void hg_cap_render(uint32_t prim, const void *verts, uint32_t count, const uint32_t *block, uint32_t konst, int noclip)
{
    uint32_t tex = HG_CAP_NOTEX;
    if (!hg_cap_active() || !verts || count > 32 || !hg_readable(verts, count * 36)) return;
    if (block) tex = texture_id(block);
    rec_head(HG_CAP_REND, 5 * 4 + count * 36);
    put_u32(prim); put_u32(count); put_u32(tex); put_u32(konst); put_u32(noclip ? 1u : 0u);
    put_bytes(verts, count * 36);
}

void hg_cap_caller(uint32_t address)
{
    static uint32_t last;
    if (!hg_cap_active() || address == last) return;
    last = address;
    rec_head(HG_CAP_CALL, 4); put_u32(address);
}

void hg_cap_setstate(uint32_t state, uint32_t value)
{
    if (!hg_cap_active()) return;
    rec_head(HG_CAP_STAT, 8); put_u32(state); put_u32(value);
}

void hg_cap_frame(uint32_t frame, const uint16_t *overlay, int has_overlay, int has_ref)
{
    uint32_t i = 0, bytes = 8;
    if (!hg_cap_active()) return;
    if (has_overlay) {                                      /* measure first: the record header holds the size */
        while (i < HG_CAP_OVERLAY_WORDS) {
            uint32_t s = i, l;
            while (i < HG_CAP_OVERLAY_WORDS && overlay[i] == g_prev[i]) i++;
            l = i;
            while (i < HG_CAP_OVERLAY_WORDS && overlay[i] != g_prev[i]) i++;
            (void)s; bytes += 8 + (i - l) * 2;
        }
    }
    rec_head(HG_CAP_FRAM, bytes); put_u32(frame); put_u32((has_overlay ? 1u : 0u) | (has_ref ? 2u : 0u));
    if (has_overlay) {
        i = 0;
        while (i < HG_CAP_OVERLAY_WORDS) {
            uint32_t s = i, l, e, k;
            while (i < HG_CAP_OVERLAY_WORDS && overlay[i] == g_prev[i]) i++;
            l = i;
            while (i < HG_CAP_OVERLAY_WORDS && overlay[i] != g_prev[i]) i++;
            e = i;
            put_u32(l - s); put_u32(e - l);
            for (k = l; k < e; k++) { uint16_t d = (uint16_t)(overlay[k] ^ g_prev[k]); put_bytes(&d, 2); g_prev[k] = overlay[k]; }
        }
    }
}

void hg_cap_close(void)
{
    flush();
    if (g_f) CloseHandle(g_f);
    g_f = 0;
}
