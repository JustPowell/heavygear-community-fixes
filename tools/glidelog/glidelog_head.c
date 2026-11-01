/* glidelog - logging proxy for glide2x.dll (Heavy Gear 3Dfx renderer diagnosis).
   Put this as C:\HeavyGear\glide2x.dll and the real driver as C:\HeavyGear\glide2x_real.dll.
   Writes C:\HeavyGear\glidelog.txt.  Freestanding: only kernel32 imports. */
typedef unsigned int U;
typedef void *HMOD;
typedef void *HANDLE;
__declspec(dllimport) HMOD __stdcall LoadLibraryA(const char *);
__declspec(dllimport) void *__stdcall GetProcAddress(HMOD, const char *);
__declspec(dllimport) U __stdcall GetModuleFileNameA(HMOD, char *, U);
__declspec(dllimport) HANDLE __stdcall CreateFileA(const char *, U, U, void *, U, U, HANDLE);
__declspec(dllimport) int __stdcall WriteFile(HANDLE, const void *, U, U *, void *);
__declspec(dllimport) int __stdcall FlushFileBuffers(HANDLE);
__declspec(dllimport) int __stdcall CloseHandle(HANDLE);
__declspec(dllimport) int __stdcall ReadFile(HANDLE, void *, U, U *, void *);
__declspec(dllimport) int __stdcall QueryPerformanceCounter(long long *);
__declspec(dllimport) int __stdcall QueryPerformanceFrequency(long long *);
/* Particle fix is on by default; the word "nofix" in glidefix.cfg next to the DLL turns it off. */
static U fx_fix = 1, fx_lastkey;
static U fx_texsource(U, U, U, U);
static int has_word(const char *buf, int n, const char *w) { int i, k, wl = 0; while (w[wl]) wl++;
    for (i = 0; i + wl <= n; i++) { for (k = 0; k < wl && buf[i + k] == w[k]; k++); if (k == wl) return 1; } return 0; }

static HANDLE logf = (HANDLE)-1;
static char lb[512]; static int lp;
static U frame, ntri_since, cur_ck_mode, cur_ck_val, cur_blend[2], cur_alc[3], cur_coc[3], cur_tex_data, cur_tex_fmt, logged_tex;
static U last_pal[256]; static int have_pal;
/* "summary" in glidelog.txt: suppress the per-call lines of the hot state setters and write only the pattern table. */
static U quiet, force_line, cur_tex_lod[3], cur_fog;
struct pat;
static struct pat *cur_pat;

static void put_s(const char *s) { while (*s && lp < 500) lb[lp++] = *s++; }
static void put_x(U v) { static const char h[] = "0123456789abcdef"; char t[8]; int i;
    for (i = 7; i >= 0; i--) { t[i] = h[v & 15]; v >>= 4; } for (i = 0; i < 8; i++) lb[lp++] = t[i]; }
static void put_d(U v) { char t[12]; int n = 0; if (!v) { lb[lp++] = '0'; return; }
    while (v) { t[n++] = '0' + v % 10; v /= 10; } while (n) lb[lp++] = t[--n]; }
static void flush_line(void) { U w; if (quiet && !force_line) { lp = 0; return; } lb[lp++] = '\n'; if (logf != (HANDLE)-1) WriteFile(logf, lb, lp, &w, 0); lp = 0; }
static void hdr(const char *name) { lp = 0; put_d(frame); put_s(" "); put_s(name); put_s("("); }

static void log_grChromakeyMode(U m) { cur_pat = 0; cur_ck_mode = m; hdr("ChromakeyMode"); put_d(m); put_s(")"); flush_line(); }
static void log_grChromakeyValue(U v) {
    int i, exact = -1, masked = -1;
    cur_pat = 0; cur_ck_val = v; hdr("ChromakeyValue"); put_x(v); put_s(")");
    if (have_pal) { for (i = 0; i < 256; i++) { if (exact < 0 && last_pal[i] == v) exact = i;
                      if (masked < 0 && ((last_pal[i] ^ v) & 0xffffff) == 0) masked = i; }
        put_s(" pal_exact="); if (exact < 0) put_s("none"); else put_d(exact);
        put_s(" pal_rgb="); if (masked < 0) put_s("none"); else put_d(masked); }
    flush_line(); }
static void log_grTexSource(U tmu, U start, U eo, U info) {
    U *in = (U *)info; cur_pat = 0; cur_tex_data = in ? in[4] : 0; cur_tex_fmt = in ? in[3] : 0; logged_tex = 0;
    cur_tex_lod[0] = in ? in[0] : 0; cur_tex_lod[1] = in ? in[1] : 0; cur_tex_lod[2] = in ? in[2] : 0;
    hdr("TexSource"); put_d(tmu); put_s(","); put_x(start); put_s(","); put_d(eo);
    if (in) { put_s(", lod "); put_d(in[0]); put_s("-"); put_d(in[1]); put_s(" asp "); put_d(in[2]);
              put_s(" fmt "); put_d(in[3]); put_s(" data "); put_x(in[4]); }
    put_s(") ck="); put_d(cur_ck_mode); put_s("/"); put_x(cur_ck_val); flush_line(); }
static void log_grTexDownloadTable(U tmu, U type, U data) {
    U *p = (U *)data; int i, topnz = 0, idx0 = -1;
    hdr("TexDownloadTable"); put_d(tmu); put_s(","); put_d(type); put_s(","); put_x(data); put_s(")");
    if (type == 2 && p) { for (i = 0; i < 256; i++) { last_pal[i] = p[i]; if (p[i] >> 24) topnz++;
                                                   if (idx0 < 0 && (p[i] & 0xffffff) == 0) idx0 = i; }
        have_pal = 1; put_s(" pal0="); put_x(p[0]); put_s(" pal1="); put_x(p[1]); put_s(" pal255="); put_x(p[255]);
        put_s(" top_nonzero="); put_d(topnz); put_s(" first_black="); if (idx0 < 0) put_s("none"); else put_d(idx0); }
    flush_line(); }
static void log_grTexDownloadMipMap(U tmu, U start, U eo, U info) {
    U *in = (U *)info; hdr("TexDownloadMipMap"); put_d(tmu); put_s(","); put_x(start); put_s(","); put_d(eo);
    if (in) { put_s(", lod "); put_d(in[0]); put_s("-"); put_d(in[1]); put_s(" asp "); put_d(in[2]);
              put_s(" fmt "); put_d(in[3]); put_s(" data "); put_x(in[4]);
              if (in[3] == 5 && in[4]) { unsigned char *d = (unsigned char *)in[4]; put_s(" texel0 "); put_d(d[0]); } }
    put_s(")"); flush_line(); }
/* Draw patterns. The plugin clips each polygon into one fixed buffer and draws it as a fan, grDrawTriangle(v0, v[i], v[i+1]),
   so consecutive triangles with the same first vertex and b == previous c belong to one polygon with (triangles + 2) vertices.
   Every distinct render state gets a row: how many polygons, how many triangles, and how many polygons had 3, 4, ... vertices. */
#define NPAT 96
struct pat { U key[14]; U polys, tris, other, hist[10]; };
static struct pat pats[NPAT]; static U npats;
static struct pat *run_pat; static U run_ax, run_ay, run_cx, run_cy, run_len;
static struct pat *find_pat(void) {
    U k[14] = { cur_tex_fmt, cur_tex_lod[0], cur_tex_lod[1], cur_tex_lod[2], cur_ck_mode, cur_blend[0], cur_blend[1],
                cur_alc[0], cur_alc[1], cur_alc[2], cur_coc[0], cur_coc[1], cur_coc[2], cur_fog };
    U i, j;
    for (i = 0; i < npats; i++) { for (j = 0; j < 14 && pats[i].key[j] == k[j]; j++); if (j == 14) return &pats[i]; }
    if (npats == NPAT) return &pats[NPAT - 1];   /* overflow bucket */
    for (j = 0; j < 14; j++) pats[npats].key[j] = k[j];
    return &pats[npats++];
}
static void close_run(void) { if (run_len) { U v = run_len + 2; if (v > 9) v = 9; run_pat->hist[v]++; run_len = 0; } }
static void track_tri(U a, U b, U c) {
    const U *va = (const U *)a, *vb = (const U *)b, *vc = (const U *)c;
    struct pat *p = cur_pat ? cur_pat : (cur_pat = find_pat());
    p->tris++;
    /* compare vertex coordinates, not pointers: the plugin copies vertices into temporaries before drawing */
    if (run_len && p == run_pat && va[0] == run_ax && va[1] == run_ay && vb[0] == run_cx && vb[1] == run_cy) { run_len++; run_cx = vc[0]; run_cy = vc[1]; }
    else { close_run(); run_pat = p; run_ax = va[0]; run_ay = va[1]; run_cx = vc[0]; run_cy = vc[1]; run_len = 1; p->polys++; }
}
static void track_poly(U n) {
    struct pat *p = cur_pat ? cur_pat : (cur_pat = find_pat());
    close_run(); p->polys++; if (n > 2) p->tris += n - 2; if (n > 9) n = 9; if (n < 10) p->hist[n]++;
}
static void dump_patterns(const char *why) {
    U i, v; U was = force_line; force_line = 1; close_run();
    hdr("PATTERNS"); put_s(why); put_s(" frame "); put_d(frame); put_s(" rows "); put_d(npats); put_s(")"); flush_line();
    for (i = 0; i < npats; i++) { struct pat *p = &pats[i];
        hdr("PAT"); put_d(i); put_s(") fmt "); put_d(p->key[0]); put_s(" lod "); put_d(p->key[2]); put_s("-"); put_d(p->key[1]);
        put_s(" asp "); put_d(p->key[3]); put_s(" ck "); put_d(p->key[4]); put_s(" blend "); put_d(p->key[5]); put_s(","); put_d(p->key[6]);
        put_s(" acomb "); put_d(p->key[7]); put_s(","); put_d(p->key[8]); put_s(","); put_d(p->key[9]);
        put_s(" ccomb "); put_d(p->key[10]); put_s(","); put_d(p->key[11]); put_s(","); put_d(p->key[12]); put_s(" fog "); put_d(p->key[13]);
        put_s(" polys "); put_d(p->polys); put_s(" tris "); put_d(p->tris); put_s(" verts");
        for (v = 3; v < 10; v++) if (p->hist[v]) { put_s(" "); put_d(v); if (v == 9) put_s("+"); put_s(":"); put_d(p->hist[v]); }
        put_s(" lines/points "); put_d(p->other); flush_line(); }
    force_line = was;
}
static void note_draw(void);
static void log_draw(const char *what, U v0) {
    note_draw();
    U *v = (U *)v0; ntri_since++;
    if (logged_tex) return; logged_tex = 1;
    hdr(what); put_s("first) tex "); put_x(cur_tex_data); put_s(" fmt "); put_d(cur_tex_fmt);
    put_s(" ck "); put_d(cur_ck_mode); put_s("/"); put_x(cur_ck_val);
    put_s(" blend "); put_d(cur_blend[0]); put_s(","); put_d(cur_blend[1]);
    put_s(" acomb "); put_d(cur_alc[0]); put_s(","); put_d(cur_alc[1]); put_s(","); put_d(cur_alc[2]);
    put_s(" ccomb "); put_d(cur_coc[0]); put_s(","); put_d(cur_coc[1]); put_s(","); put_d(cur_coc[2]);
    if (v) { put_s(" v0.rgba "); put_x(v[3]); put_s(" "); put_x(v[4]); put_s(" "); put_x(v[5]); put_s(" "); put_x(v[7]); }
    flush_line(); }
static void log_grDrawTriangle(U a, U b, U c) { track_tri(a, b, c); log_draw("DrawTriangle", a); }
static void log_grFogMode(U m) { cur_pat = 0; cur_fog = m; hdr("FogMode"); put_d(m); put_s(")"); flush_line(); }
static void log_grDrawPolygonVertexList(U n, U vl) { track_poly(n); log_draw("DrawPolygonVertexList", vl); }
static void log_grAADrawLine(U a, U b) { (cur_pat ? cur_pat : (cur_pat = find_pat()))->other++; log_draw("AADrawLine", a); }
static void log_grDrawPoint(U a) { (cur_pat ? cur_pat : (cur_pat = find_pat()))->other++; log_draw("DrawPoint", a); }
static void log_grDrawLine(U a, U b) { (cur_pat ? cur_pat : (cur_pat = find_pat()))->other++; log_draw("DrawLine", a); }
static void log_grColorCombine(U f, U fa, U l, U o, U inv) { cur_pat = 0; cur_coc[0] = f; cur_coc[1] = l; cur_coc[2] = o;
    hdr("ColorCombine"); put_d(f); put_s(","); put_d(fa); put_s(","); put_d(l); put_s(","); put_d(o); put_s(","); put_d(inv); put_s(")"); flush_line(); }
static void log_grAlphaCombine(U f, U fa, U l, U o, U inv) { cur_pat = 0; cur_alc[0] = f; cur_alc[1] = l; cur_alc[2] = o;
    hdr("AlphaCombine"); put_d(f); put_s(","); put_d(fa); put_s(","); put_d(l); put_s(","); put_d(o); put_s(","); put_d(inv); put_s(")"); flush_line(); }
static void log_grAlphaBlendFunction(U a, U b, U c, U d) { cur_pat = 0; cur_blend[0] = a; cur_blend[1] = b;
    hdr("AlphaBlendFunction"); put_d(a); put_s(","); put_d(b); put_s(","); put_d(c); put_s(","); put_d(d); put_s(")"); flush_line(); }
static void log_grTexCombine(U t, U rf, U rfa, U af, U afa, U ri, U ai) {
    hdr("TexCombine"); put_d(t); put_s(","); put_d(rf); put_s(","); put_d(rfa); put_s(","); put_d(af); put_s(","); put_d(afa);
    put_s(","); put_d(ri); put_s(","); put_d(ai); put_s(")"); flush_line(); }
static void log_grConstantColorValue(U v) { hdr("ConstantColorValue"); put_x(v); put_s(")"); flush_line(); }
/* Frame timing, written every 240 swaps even in summary mode, to compare with the hgd3d9 plugin's own numbers. */
static long long ft_last, ft_freq, ft_sum, ft_first_draw, ft_last_draw, ft_sum_b, ft_sum_c; static U ft_slow, ft_n;
static void note_draw(void) { long long t; QueryPerformanceCounter(&t); if (!ft_first_draw) ft_first_draw = t; ft_last_draw = t; }
static void frame_timing(void) {
    long long now; double ms;
    QueryPerformanceCounter(&now);
    if (ft_first_draw) { ft_sum_b += ft_last_draw - ft_first_draw; ft_sum_c += now - ft_last_draw; }
    ft_first_draw = ft_last_draw = 0;
    if (!ft_freq) QueryPerformanceFrequency(&ft_freq);
    if (ft_last && ft_freq > 0) {
        ms = (double)(now - ft_last) * 1000.0 / (double)ft_freq; ft_sum += now - ft_last; ft_n++;
        if (ms >= 60.0) ft_slow++;
        if (ft_n == 240) { U was = force_line; force_line = 1;
            hdr("FRAMES"); put_s("240 frames, average x0.1 ms "); put_d((U)((double)ft_sum * 10000.0 / (double)ft_freq / 240.0));
            put_s(", frames over 60 ms "); put_d(ft_slow);
            put_s(", first-to-last draw x0.1 ms "); put_d((U)((double)ft_sum_b * 10000.0 / (double)ft_freq / 240.0));
            put_s(", last draw to swap x0.1 ms "); put_d((U)((double)ft_sum_c * 10000.0 / (double)ft_freq / 240.0)); put_s(")"); flush_line(); force_line = was;
            ft_n = 0; ft_sum = 0; ft_slow = 0; ft_sum_b = 0; ft_sum_c = 0; }
    }
    ft_last = now;
}
static void log_grBufferSwap(U i) { frame_timing(); hdr("BufferSwap"); put_s(") tris "); put_d(ntri_since); flush_line(); ntri_since = 0; frame++;
    if (frame % 240 == 0) dump_patterns("periodic");
    if ((frame & 63) == 0 && logf != (HANDLE)-1) FlushFileBuffers(logf); }
/* Counts grSstWinOpen calls: the game closes and reopens Glide around an alt-tab, and textures uploaded before do not
   carry over, so the particle fix forgets its converted ones when this changes. */
static U fx_windows;
static void log_grSstWinOpen(U a, U b, U c, U d, U e, U f, U g) { fx_windows++; hdr("SstWinOpen"); put_x(a); put_s(","); put_d(b);
    put_s(","); put_d(c); put_s(","); put_d(d); put_s(","); put_d(e); put_s(","); put_d(f); put_s(","); put_d(g); put_s(")"); flush_line(); }
static void log_grGlideShutdown(void) { dump_patterns("shutdown"); hdr("GlideShutdown"); put_s(")"); flush_line(); if (logf != (HANDLE)-1) FlushFileBuffers(logf); }

/* The MSVC-style toolchain wants this symbol whenever floating point is used and there is no CRT. */
int _fltused = 1;
