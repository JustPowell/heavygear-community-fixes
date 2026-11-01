int __stdcall DllMain(HMOD inst, U reason, void *res) {
    if (reason == 1) {
        char path[300]; U n = GetModuleFileNameA(inst, path, 260), i, cut = 0;
        for (i = 0; i < n; i++) if (path[i] == '\\') cut = i + 1;
        { const char *a = "glide2x_real.dll"; U k = 0; while (a[k]) { path[cut + k] = a[k]; k++; } path[cut + k] = 0; }
        HMOD h = LoadLibraryA(path);
        if (!h) return 0;
        resolve(h);
        { const char *a = "glidelog.txt"; U k = 0; while (a[k]) { path[cut + k] = a[k]; k++; } path[cut + k] = 0; }
        /* GENERIC_WRITE, FILE_SHARE_READ|WRITE (the game runs as more than one process), OPEN_ALWAYS; append */
        logf = CreateFileA(path, 0x40000000, 3, 0, 3, 0x80, 0);  /* OPEN_EXISTING: log only if glidelog.txt exists */
        if (logf != (HANDLE)-1) { __declspec(dllimport) U __stdcall SetFilePointer(HANDLE, int, int *, U);
                                  SetFilePointer(logf, 0, 0, 2); }
        if (logf != (HANDLE)-1) { HANDLE c = CreateFileA(path, 0x80000000, 3, 0, 3, 0x80, 0);
          if (c != (HANDLE)-1) { char b[256]; U got = 0; ReadFile(c, b, 255, &got, 0); quiet = has_word(b, got, "summary"); } }
        { const char *a = "glidefix.cfg"; U k = 0; HANDLE c; while (a[k]) { path[cut + k] = a[k]; k++; } path[cut + k] = 0;
          c = CreateFileA(path, 0x80000000, 3, 0, 3, 0x80, 0);
          if (c != (HANDLE)-1) { char b[256]; U got = 0; ReadFile(c, b, 255, &got, 0); fx_fix = !has_word(b, got, "nofix"); } }
        hdr("---- glidelog attached"); put_s(fx_fix ? " particle fix on" : " particle fix off"); put_s(quiet ? ", summary only" : ", full log"); put_s(")"); flush_line();
    }
    return 1;
}

/* Particle fix. The game draws smoke, dust and fire as keyed P_8 textures whose transparency lives in the palette's top
   byte (0xFF = transparent, lower = more opaque); the chroma key colour does not match the background, so the driver draws
   black squares. We convert each such texture to AP_88 (8-bit alpha + palette index, so the palette still applies), with
   alpha = 255 - top byte and key texels transparent, store it in the top 128 KB of texture memory (the game keeps that free;
   its PreloadTexture leaves 0x20000) and turn the chroma key off.
   Most particles are not keyed, though: the game draws them with the key off, blended by the texture's alpha
   (SRC_ALPHA, 1-SRC_ALPHA; alpha combine SCALE_OTHER with the texture as other), which a P_8 texture does not have, so
   they come out solid. Those are converted the same way, without a key colour. (Found with nGlide 2.10, 2026-10-31: the
   keyed ones are a few hundred of the particle draws, the keyless ones most of them. After an alt-tab the game uploads
   its particles as AP_88 itself, which is why they looked right from then on.)
   A slot is 4 KB: textures up to 32x32 with their smaller levels (AP_88 is 2 bytes a texel). */
static U ck_cache_key[32][4]; static U ck_next; static unsigned short ck_buf[8192];
static U ck_hash(const unsigned char *d, U n, U h) { U i; for (i = 0; i < n; i++) h = (h ^ d[i]) * 16777619u; return h; }
static U fx_texsource(U tmu, U start, U eo, U info) {
    U *in = (U *)info, large, small, lod, total = 0, size, i, slot, hash, key, addr;
    U alpha_blended = cur_blend[0] == 1 && cur_blend[1] == 5 && cur_alc[0] == 3 && cur_alc[2] == 1;
    static U info2[5]; const unsigned char *d;
    if (!fx_fix || !(cur_ck_mode || alpha_blended) || !in || in[3] != 5 || in[2] != 3 || !have_pal || tmu != 0)
        return r_grTexSource(tmu, start, eo, info);
    key = cur_ck_mode ? fx_lastkey & 0xffffff : 0xffffffffu;      /* keyless: no palette entry matches */
    small = in[0]; large = in[1]; d = (const unsigned char *)in[4];
    if (!d || large > 8 || small > 8 || small < large || (256u >> large) > 32) return r_grTexSource(tmu, start, eo, info);
    { static U seen_windows; if (seen_windows != fx_windows) {    /* a new Glide window: nothing converted is uploaded */
          seen_windows = fx_windows; for (slot = 0; slot < 32; slot++) ck_cache_key[slot][2] = 0; } }
    for (lod = large; lod <= small; lod++) { size = 256u >> lod; total += size * size; }
    hash = ck_hash(d, total, 2166136261u); hash = ck_hash((const unsigned char *)last_pal, 1024, hash); hash ^= key;
    for (slot = 0; slot < 32; slot++) if (ck_cache_key[slot][0] == in[4] && ck_cache_key[slot][1] == hash && ck_cache_key[slot][2]) break;
    addr = (r_grTexMaxAddress(0) - 0x20000u + 7) & ~7u;
    if (slot == 32) {
        unsigned short *o = ck_buf; U k = 0;
        slot = ck_next; ck_next = (ck_next + 1) & 31;
        for (lod = large; lod <= small; lod++) { size = 256u >> lod; size *= size;
            for (i = 0; i < size; i++) { U idx = d[k++], e = last_pal[idx], a = 255 - (e >> 24);
                if ((e & 0xffffff) == key) a = 0;
                *o++ = (unsigned short)((a << 8) | idx); } }
        info2[0] = small; info2[1] = large; info2[2] = 3; info2[3] = 0xe; info2[4] = (U)ck_buf;
        r_grTexDownloadMipMap(0, addr + slot * 0x1000, eo, (U)info2);
        hdr("particle fix converted"); put_x(in[4]); put_s(" key "); put_x(key); put_s(" levels "); put_d(large); put_s("-"); put_d(small); put_s(" slot "); put_d(slot); put_s(")"); flush_line();
        ck_cache_key[slot][0] = in[4]; ck_cache_key[slot][1] = hash; ck_cache_key[slot][2] = 1;
    }
    info2[0] = small; info2[1] = large; info2[2] = 3; info2[3] = 0xe; info2[4] = 0;
    return r_grTexSource(0, addr + slot * 0x1000, eo, (U)info2);
}

/* Reads the 640x480 RGB565 back buffer from the real driver and saves it as a 24-bit BMP. hgd3d9 (tee mode) calls this at the
 * moments it saves its own frame, so the native and the D3D9 picture of the same frame can be compared. Returns 1 on success. */
static unsigned short nat_buf[640 * 480];
static unsigned char nat_bmp[54 + 640 * 480 * 3];
U __stdcall hgCaptureNative(const char *path) {
    U x, y, w = 0, n = 54 + 640 * 480 * 3; HANDLE f;
    if (!r_grLfbReadRegion) return 0;
    if (!r_grLfbReadRegion(1 /* GR_BUFFER_BACKBUFFER */, 0, 0, 640, 480, 640 * 2, (U)nat_buf)) return 0;
    for (x = 0; x < 54; x++) nat_bmp[x] = 0;
    nat_bmp[0] = 'B'; nat_bmp[1] = 'M';
    nat_bmp[2] = (unsigned char)n; nat_bmp[3] = (unsigned char)(n >> 8); nat_bmp[4] = (unsigned char)(n >> 16); nat_bmp[5] = (unsigned char)(n >> 24);
    nat_bmp[10] = 54; nat_bmp[14] = 40; nat_bmp[18] = 640 & 255; nat_bmp[19] = 640 >> 8; nat_bmp[22] = 480 & 255; nat_bmp[23] = 480 >> 8;
    nat_bmp[26] = 1; nat_bmp[28] = 24;
    for (y = 0; y < 480; y++) {
        unsigned char *o = nat_bmp + 54 + (479 - y) * 640 * 3;
        for (x = 0; x < 640; x++) {
            unsigned short p = nat_buf[y * 640 + x]; U r = (p >> 11) & 31, g = (p >> 5) & 63, b = p & 31;
            o[3 * x] = (unsigned char)((b << 3) | (b >> 2)); o[3 * x + 1] = (unsigned char)((g << 2) | (g >> 4)); o[3 * x + 2] = (unsigned char)((r << 3) | (r >> 2));
        }
    }
    f = CreateFileA(path, 0x40000000, 0, 0, 2, 0x80, 0);
    if (f == (HANDLE)-1) return 0;
    WriteFile(f, nat_bmp, n, &w, 0); CloseHandle(f);
    return w == n;
}
