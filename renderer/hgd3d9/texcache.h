/* texcache.h - turns the game's Texture block (the `arg` of Render) into a backend texture, once, and keeps it.
 *
 * Layout read from the v1.2 3Dfx plugin (FUN_10002410, FUN_10002500, FUN_10002760) and from runtime dumps; see
 * docs/research/renderer-interface.md section 6:
 *   block[0]        pointer to the descriptor
 *   desc[0], desc[1] width and height as powers of two (a mip bitmask whose highest bit is the base size)
 *   desc[2]         pointer to w*h 8-bit palette indices. The 3Dfx plugin uses this pointer as the cache key.
 *   desc[3]         pointer to the palette, 32-bit entries 0x00RRGGBB; the top byte is transparency.
 *   desc[4]         chroma-key palette index (meaningful only for keyed primitives; garbage otherwise)
 *   desc[6]         1 = alpha-palette texture (alpha from the palette's top byte)
 * The palette length is not stored; when the pixels follow the palette in memory it is the distance between them, else 256.
 */
#ifndef HG_TEXCACHE_H
#define HG_TEXCACHE_H

#include "backend.h"

/* A texture block read into plain values (also used by the capture recorder). */
typedef struct HgTexSrc {
    const uint32_t *desc, *pal;
    const uint8_t  *pix;
    uint32_t        w, h, npal;
    uint32_t        desc_raw[5];     /* desc[0], desc[1], desc[4], desc[5], desc[6] */
} HgTexSrc;

/* Parse the block: 0 on success, non-zero if it is not readable or not a texture. */
int hg_tex_source(const uint32_t *block, HgTexSrc *s);

/* The texture for `block` (at least 8 readable words), or NULL if the block is not usable. `keyed` is the 3Dfx plugin's
 * chroma-key flag for the primitive being drawn (prims 3, 4, 7, 8, 10 to 13): the key colour is palette[desc[4]] and its
 * texels become transparent. Textures with desc[6] == 1, and all keyed textures, take alpha from the palette's top byte (255 - byte);
 * others are opaque. */
HgTex *hg_texcache_get(const HgBackend *be, const uint32_t *block, uint32_t frame, int keyed);

/* Cumulative counts of backend texture creations and updates, for finding stalls. */
void hg_texcache_stats(uint32_t *creates, uint32_t *updates);

/* Destroy every cached texture (display loss, shutdown). */
void hg_texcache_clear(const HgBackend *be);

uint32_t hg_texcache_count(void);

/* Keyed textures whose key index is past the end of the palette use black as the key colour (the entry past the end of a palette reads as 0). */
void hg_texcache_set_black_key(int on);
void hg_texcache_set_bleed_params(uint32_t solid, uint32_t passes);
void hg_texcache_set_bleed(int on);   /* default on: transparent texels take their neighbours' colour (no dark halo from filtering) */

#endif
