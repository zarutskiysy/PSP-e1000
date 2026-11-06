/*
 * scr_codec.h — second-screen decoder: plain C99, no malloc, no libc beyond memcpy/memset.
 * Compiles with psp-gcc (PSP app) and clang (macOS: host tests + libscrcodec.dylib used by
 * tools/fake_psp_screen.py through ctypes), so the Mac tests run the exact PSP decode code.
 */
#ifndef SCR_CODEC_H
#define SCR_CODEC_H

#include <stddef.h>
#include <stdint.h>

#include "../proto_screen.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint16_t *canvas;  /* SCR_W x SCR_H pixels (PSP 565), row stride `stride` pixels */
    uint32_t stride;
    uint8_t dirty[SCR_NTILES]; /* tiles written since the last scr_present() */
    uint32_t frame_id;  /* frame currently being assembled */
    uint16_t next_chunk;
    int in_frame;       /* chunks of frame_id seen, LAST not yet seen */
    int synced;         /* a keyframe was fully received and nothing was lost since */
    int need_key;       /* report SCR_ACKF_NEED_KEY in the next ACK */
    /* stats */
    uint32_t frames_done, chunks, tiles, solid_tiles, errors, gaps;
    uint32_t last_frame_id;
} scr_decoder_t;

enum {
    SCR_DEC_OK = 0,          /* chunk applied, frame not finished */
    SCR_DEC_FRAME_DONE = 1,  /* chunk applied and it was the LAST chunk: present + ACK now */
    SCR_DEC_E_SHORT = -1,    /* payload shorter than the header */
    SCR_DEC_E_CODEC = -2,    /* unknown codec */
    SCR_DEC_E_LZ4 = -3,      /* corrupt LZ4 block / size mismatch */
    SCR_DEC_E_BODY = -4,     /* records overrun the body or a bad tile index */
    SCR_DEC_E_SCRATCH = -5   /* body_len larger than the scratch buffer */
};

void scr_dec_init(scr_decoder_t *d, uint16_t *canvas, uint32_t stride);

/* Applies one SCR_CHUNK payload. scratch (>= body_len bytes, SCR_MAX_BODY is enough) is used
 * only for LZ4 bodies. Returns SCR_DEC_*. Errors bump d->errors and set d->need_key. */
int scr_dec_chunk(scr_decoder_t *d, const uint8_t *payload, uint32_t len, uint8_t *scratch, uint32_t scratch_cap);

/* Copies every dirty tile (or all tiles when all != 0) from the canvas to dst (stride in
 * pixels, e.g. the PSP framebuffer with stride 512) and clears the dirty map.
 * Returns the number of tiles copied. dst may equal the canvas (then it only clears). */
int scr_present(scr_decoder_t *d, uint16_t *dst, uint32_t dst_stride, int all);

/* Marks the tiles covering rows [y0, y1) dirty (e.g. under an overlay that must be restored). */
void scr_mark_rows_dirty(scr_decoder_t *d, int y0, int y1);

/* Safe LZ4 block decoder (format: https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md).
 * Returns decompressed size, or -1 on malformed input / output overflow. */
int scr_lz4_decompress(const uint8_t *src, uint32_t src_len, uint8_t *dst, uint32_t dst_cap);

/* sizeof(scr_decoder_t), so the ctypes mirror in tools/fake_psp_screen.py can check its layout. */
uint32_t scr_dec_struct_size(void);

#ifdef __cplusplus
}
#endif
#endif
