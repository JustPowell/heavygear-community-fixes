/* capture.h - the capture file: a recording of everything the engine told the renderer plugin, so a run can be replayed without the
 * game by an offline replay tool. Written by the plugin when hgd3d9.capture exists in the game folder.
 *
 * Little endian. A 16-byte header, then records of { u32 tag, u32 payload bytes, payload }:
 *   INIT  n, info[n]                       FirstDevice's DeviceInfo words
 *   TEXT  id, w, h, npal, desc0, desc1, desc4, desc5, desc6, pal[npal], pix[w*h]     a texture, the first time its content is seen
 *   REND  prim, count, tex id (0xffffffff none), constant word (arg[1]), flags (bit 0 RenderNoClip), verts[count] of 36 bytes
 *   STAT  state, value                     a SetState call
 *   CALL  address                          the engine address that called Render for the REND records that follow (written when it changes; for finding
 *                                          which part of the engine emits a draw); readers may ignore it
 *   FRAM  frame, flags, overlay delta      end of a frame (RefreshDisplay). flags bit 0: the 2D layer follows; bit 1: reference
 *                                          pictures exist for this frame (hgnat_NNNN.bmp from the real plugin, hgcap_NNNN.bmp from the
 *                                          live plugin). The delta is the 2D layer (RGB565, 640x480) XOR the previous frame's, as
 *                                          runs: { u32 skip words, u32 literal words, u16 literals[] } until all 307200 words are covered.
 */
#ifndef HG_CAPTURE_H
#define HG_CAPTURE_H

#include <stdint.h>

#define HG_CAP_MAGIC "HGCAP001"
enum { HG_CAP_INIT = 1, HG_CAP_TEXT = 2, HG_CAP_REND = 3, HG_CAP_STAT = 4, HG_CAP_FRAM = 5, HG_CAP_CALL = 6 };
#define HG_CAP_NOTEX 0xffffffffu
#define HG_CAP_OVERLAY_WORDS (640 * 480)

#ifdef HG_CAP_RECORDER
/* Recorder side (the plugin). All calls are cheap no-ops until hg_cap_open succeeds. */
int  hg_cap_open(const char *path);
int  hg_cap_active(void);
void hg_cap_init(const uint32_t *info, uint32_t n);
/* `block` is the texture block for textured primitives, `konst` the arg[1] word for the constant-colour ones. */
void hg_cap_render(uint32_t prim, const void *verts, uint32_t count, const uint32_t *block, uint32_t konst, int noclip);
void hg_cap_caller(uint32_t address);
void hg_cap_setstate(uint32_t state, uint32_t value);
void hg_cap_frame(uint32_t frame, const uint16_t *overlay, int has_overlay, int has_ref);
void hg_cap_close(void);
#endif

#endif
