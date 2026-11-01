/* null_backend.c - a backend that draws nothing. Lets the plugin load, run and be logged before a GPU backend exists. */
#include "backend.h"

static int      nb_init(const HgInitParams *p) { (void)p; return 0; }
static void     nb_shutdown(void) {}
static int      nb_restore(void) { return 0; }
static HgTex   *nb_tex_create(uint32_t w, uint32_t h, const uint32_t *argb, uint32_t flags) { (void)w; (void)h; (void)argb; (void)flags; return (HgTex *)0; }
static int      nb_tex_update(HgTex *t, uint32_t w, uint32_t h, const uint32_t *argb) { (void)t; (void)w; (void)h; (void)argb; return 0; }
static void     nb_tex_destroy(HgTex *t) { (void)t; }
static void     nb_draw_fan(const HgVertex *v, uint32_t n, HgTex *tex, const HgDrawState *st) { (void)v; (void)n; (void)tex; (void)st; }
static void     nb_set_mipmaps(int on) { (void)on; }
static void     nb_draw_outline(const HgVertex *v, uint32_t n, const HgDrawState *st) { (void)v; (void)n; (void)st; }
static void     nb_draw_points(const HgVertex *v, uint32_t n, const HgDrawState *st) { (void)v; (void)n; (void)st; }
static void     nb_set_fog_color(uint32_t rgb) { (void)rgb; }
static void     nb_clear_depth(void) {}
static void     nb_draw_overlay(const HgOverlay *o) { (void)o; }
static void     nb_present(void) {}

const HgBackend hg_backend_null = {
    "null", nb_init, nb_shutdown, nb_restore, nb_tex_create, nb_tex_update, nb_tex_destroy,
    nb_draw_outline, nb_draw_points, nb_set_fog_color, nb_set_mipmaps, nb_draw_fan, nb_clear_depth, nb_draw_overlay, nb_present, (int (*)(const char *))0, (int (*)(const HgLight *))0
};
