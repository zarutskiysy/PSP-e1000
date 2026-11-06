#include "scr_codec.h"

#include <string.h>

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

uint32_t scr_dec_struct_size(void) { return (uint32_t)sizeof(scr_decoder_t); }

void scr_dec_init(scr_decoder_t *d, uint16_t *canvas, uint32_t stride) {
    memset(d, 0, sizeof(*d));
    d->canvas = canvas;
    d->stride = stride;
    d->need_key = 1;
}

int scr_lz4_decompress(const uint8_t *src, uint32_t src_len, uint8_t *dst, uint32_t dst_cap) {
    const uint8_t *ip = src, *iend = src + src_len;
    uint8_t *op = dst, *oend = dst + dst_cap;
    if (src_len == 0) return -1;
    for (;;) {
        uint32_t token, lit, ml, off;
        const uint8_t *match;
        if (ip >= iend) return -1;
        token = *ip++;
        lit = token >> 4;
        if (lit == 15) {
            uint32_t b;
            do {
                if (ip >= iend) return -1;
                b = *ip++;
                lit += b;
            } while (b == 255);
        }
        if (lit > (uint32_t)(iend - ip) || lit > (uint32_t)(oend - op)) return -1;
        memcpy(op, ip, lit);
        op += lit;
        ip += lit;
        if (ip == iend) break; /* last sequence: literals only */
        if (iend - ip < 2) return -1;
        off = rd16(ip);
        ip += 2;
        if (off == 0 || off > (uint32_t)(op - dst)) return -1;
        ml = token & 15;
        if (ml == 15) {
            uint32_t b;
            do {
                if (ip >= iend) return -1;
                b = *ip++;
                ml += b;
            } while (b == 255);
        }
        ml += 4;
        if (ml > (uint32_t)(oend - op)) return -1;
        match = op - off;
        if (off >= ml) {
            memcpy(op, match, ml);
            op += ml;
        } else {
            while (ml--) *op++ = *match++; /* overlapping copy (run-length style) */
        }
    }
    return (int)(op - dst);
}

static void fill_tile(scr_decoder_t *d, uint32_t idx, uint16_t color) {
    uint16_t *row = d->canvas + (idx / SCR_TILES_X) * SCR_TILE * d->stride + (idx % SCR_TILES_X) * SCR_TILE;
    int y, x;
    for (y = 0; y < SCR_TILE; y++, row += d->stride)
        for (x = 0; x < SCR_TILE; x++) row[x] = color;
}

static void copy_tile(scr_decoder_t *d, uint32_t idx, const uint8_t *px) {
    uint16_t *row = d->canvas + (idx / SCR_TILES_X) * SCR_TILE * d->stride + (idx % SCR_TILES_X) * SCR_TILE;
    int y;
    /* Wire pixels are little-endian u16; both the PSP (MIPS LE) and arm64 are little-endian. */
    for (y = 0; y < SCR_TILE; y++, row += d->stride, px += SCR_TILE * 2) memcpy(row, px, SCR_TILE * 2);
}

static int apply_body(scr_decoder_t *d, const uint8_t *b, uint32_t blen, uint32_t n) {
    const uint8_t *end = b + blen;
    uint32_t i;
    for (i = 0; i < n; i++) {
        uint16_t tag, idx;
        if (end - b < 2) return SCR_DEC_E_BODY;
        tag = rd16(b);
        b += 2;
        idx = tag & SCR_TAG_INDEX_MASK;
        if (idx >= SCR_NTILES) return SCR_DEC_E_BODY;
        if (tag & SCR_TAG_SOLID) {
            if (end - b < 2) return SCR_DEC_E_BODY;
            fill_tile(d, idx, rd16(b));
            b += 2;
            d->solid_tiles++;
        } else {
            if (end - b < SCR_TILE_BYTES) return SCR_DEC_E_BODY;
            copy_tile(d, idx, b);
            b += SCR_TILE_BYTES;
        }
        d->dirty[idx] = 1;
        d->tiles++;
    }
    return b == end ? SCR_DEC_OK : SCR_DEC_E_BODY;
}

int scr_dec_chunk(scr_decoder_t *d, const uint8_t *p, uint32_t len, uint8_t *scratch, uint32_t scratch_cap) {
    uint32_t frame_id, n, body_len;
    uint16_t idx;
    uint8_t codec, cf;
    const uint8_t *body;
    int r;
    if (len < SCR_CHUNK_HDR) {
        d->errors++;
        d->need_key = 1;
        return SCR_DEC_E_SHORT;
    }
    frame_id = rd32(p);
    idx = rd16(p + 4);
    n = rd16(p + 6);
    codec = p[8];
    cf = p[9];
    body_len = rd32(p + 12);

    /* Sequence tracking: a gap means some tiles may be stale -> ask for a keyframe. */
    if (idx == 0) {
        if (d->in_frame) d->gaps++, d->need_key = 1, d->synced = 0; /* previous frame lost its tail */
        d->frame_id = frame_id;
        d->in_frame = 1;
        d->next_chunk = 0;
        if (cf & SCR_CF_KEY) d->synced = 1, d->need_key = 0;
    } else if (!d->in_frame || frame_id != d->frame_id || idx != d->next_chunk) {
        d->gaps++;
        d->need_key = 1;
        d->synced = 0;
        d->frame_id = frame_id;
        d->in_frame = 1;
    }
    d->next_chunk = (uint16_t)(idx + 1);
    d->chunks++;

    if (codec == SCR_CODEC_RAW) {
        body = p + SCR_CHUNK_HDR;
        if (body_len != len - SCR_CHUNK_HDR) r = SCR_DEC_E_BODY;
        else r = apply_body(d, body, body_len, n);
    } else if (codec == SCR_CODEC_LZ4) {
        if (body_len > scratch_cap) r = SCR_DEC_E_SCRATCH;
        else if (scr_lz4_decompress(p + SCR_CHUNK_HDR, len - SCR_CHUNK_HDR, scratch, body_len) != (int)body_len)
            r = SCR_DEC_E_LZ4;
        else r = apply_body(d, scratch, body_len, n);
    } else {
        r = SCR_DEC_E_CODEC;
    }
    if (r < 0) {
        d->errors++;
        d->need_key = 1;
        d->synced = 0;
    }
    if (cf & SCR_CF_LAST) {
        d->in_frame = 0;
        d->frames_done++;
        d->last_frame_id = frame_id;
        return r < 0 ? r : SCR_DEC_FRAME_DONE;
    }
    return r;
}

int scr_present(scr_decoder_t *d, uint16_t *dst, uint32_t dst_stride, int all) {
    int i, n = 0;
    for (i = 0; i < SCR_NTILES; i++) {
        if (all || d->dirty[i]) {
            if (dst != d->canvas) {
                const uint16_t *s = d->canvas + (i / SCR_TILES_X) * SCR_TILE * d->stride + (i % SCR_TILES_X) * SCR_TILE;
                uint16_t *o = dst + (i / SCR_TILES_X) * SCR_TILE * dst_stride + (i % SCR_TILES_X) * SCR_TILE;
                int y;
                for (y = 0; y < SCR_TILE; y++, s += d->stride, o += dst_stride) memcpy(o, s, SCR_TILE * 2);
            }
            d->dirty[i] = 0;
            n++;
        }
    }
    return n;
}

void scr_mark_rows_dirty(scr_decoder_t *d, int y0, int y1) {
    int ty, tx;
    if (y0 < 0) y0 = 0;
    if (y1 > SCR_H) y1 = SCR_H;
    for (ty = y0 / SCR_TILE; ty * SCR_TILE < y1; ty++)
        for (tx = 0; tx < SCR_TILES_X; tx++) d->dirty[ty * SCR_TILES_X + tx] = 1;
}
