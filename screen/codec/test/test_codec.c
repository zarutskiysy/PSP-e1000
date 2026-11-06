/* Host unit tests for scr_codec.c (clang + ASan/UBSan). Cross-tests with the Python encoder and
 * the real lz4 compressor live in screen/tests (ctypes on libscrcodec.dylib). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../scr_codec.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

static uint16_t canvas[SCR_H * SCR_W];
static uint8_t scratch[SCR_MAX_BODY];

static uint8_t *put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); return p + 2; }
static uint8_t *put32(uint8_t *p, uint32_t v) { p = put16(p, (uint16_t)v); return put16(p, (uint16_t)(v >> 16)); }

static uint32_t hdr(uint8_t *p, uint32_t fid, uint16_t idx, uint16_t n, uint8_t codec, uint8_t cf, uint32_t blen) {
    uint8_t *q = put32(p, fid);
    q = put16(q, idx); q = put16(q, n);
    *q++ = codec; *q++ = cf; q = put16(q, 0); put32(q, blen);
    return SCR_CHUNK_HDR;
}

static void test_raw_and_solid(void) {
    static uint8_t msg[SCR_MAX_PAYLOAD];
    scr_decoder_t d;
    uint8_t *b = msg + SCR_CHUNK_HDR;
    int i, r;
    scr_dec_init(&d, canvas, SCR_W);
    /* tile 31 (tx=1, ty=1) = gradient, tile 509 (last) = solid 0xF800 */
    b = put16(b, 31);
    for (i = 0; i < 256; i++) b = put16(b, (uint16_t)(i * 7));
    b = put16(b, 509 | SCR_TAG_SOLID);
    b = put16(b, 0xF800);
    hdr(msg, 5, 0, 2, SCR_CODEC_RAW, SCR_CF_KEY | SCR_CF_LAST, (uint32_t)(b - msg - SCR_CHUNK_HDR));
    r = scr_dec_chunk(&d, msg, (uint32_t)(b - msg), scratch, sizeof scratch);
    CHECK(r == SCR_DEC_FRAME_DONE);
    CHECK(d.synced && !d.need_key && d.frames_done == 1 && d.tiles == 2 && d.solid_tiles == 1);
    for (i = 0; i < 256; i++) CHECK(canvas[(16 + i / 16) * SCR_W + 16 + i % 16] == (uint16_t)(i * 7));
    CHECK(canvas[271 * SCR_W + 479] == 0xF800 && canvas[256 * SCR_W + 464] == 0xF800);
    CHECK(canvas[0] == 0);
    CHECK(d.dirty[31] && d.dirty[509] && !d.dirty[0]);
    {
        static uint16_t fb[SCR_H * 512];
        CHECK(scr_present(&d, fb, 512, 0) == 2);
        CHECK(fb[(16 + 3) * 512 + 16 + 5] == (uint16_t)((3 * 16 + 5) * 7));
        CHECK(fb[271 * 512 + 479] == 0xF800);
        CHECK(!d.dirty[31]);
        scr_mark_rows_dirty(&d, 264, 272);
        CHECK(d.dirty[16 * 30] && d.dirty[509] && !d.dirty[15 * 30]);
    }
}

static void test_errors_and_gaps(void) {
    uint8_t msg[64];
    uint8_t *b = msg + SCR_CHUNK_HDR;
    scr_decoder_t d;
    scr_dec_init(&d, canvas, SCR_W);
    CHECK(scr_dec_chunk(&d, msg, 4, scratch, sizeof scratch) == SCR_DEC_E_SHORT);
    /* bad tile index */
    b = put16(b, 600 | SCR_TAG_SOLID); b = put16(b, 1);
    hdr(msg, 1, 0, 1, SCR_CODEC_RAW, SCR_CF_KEY, 4);
    CHECK(scr_dec_chunk(&d, msg, SCR_CHUNK_HDR + 4, scratch, sizeof scratch) == SCR_DEC_E_BODY);
    CHECK(d.need_key && !d.synced);
    /* good keyframe chunk 0, then chunk 2 (gap) */
    b = msg + SCR_CHUNK_HDR; b = put16(b, 0 | SCR_TAG_SOLID); put16(b, 7);
    hdr(msg, 2, 0, 1, SCR_CODEC_RAW, SCR_CF_KEY, 4);
    CHECK(scr_dec_chunk(&d, msg, SCR_CHUNK_HDR + 4, scratch, sizeof scratch) == SCR_DEC_OK);
    CHECK(d.synced && !d.need_key);
    hdr(msg, 2, 2, 1, SCR_CODEC_RAW, SCR_CF_LAST, 4);
    CHECK(scr_dec_chunk(&d, msg, SCR_CHUNK_HDR + 4, scratch, sizeof scratch) == SCR_DEC_FRAME_DONE);
    CHECK(d.need_key && d.gaps == 2); /* unfinished frame 1 + skipped chunk 1 */
    /* unknown codec */
    hdr(msg, 3, 0, 1, 9, SCR_CF_LAST, 4);
    CHECK(scr_dec_chunk(&d, msg, SCR_CHUNK_HDR + 4, scratch, sizeof scratch) == SCR_DEC_E_CODEC);
    /* body length mismatch on raw */
    hdr(msg, 4, 0, 1, SCR_CODEC_RAW, SCR_CF_LAST, 3);
    CHECK(scr_dec_chunk(&d, msg, SCR_CHUNK_HDR + 4, scratch, sizeof scratch) == SCR_DEC_E_BODY);
}

static void test_lz4(void) {
    /* Hand-made block: literals "ab", match off=2 len=6 -> "abababab", then last literals "XYZ12" */
    const uint8_t blk[] = {0x22, 'a', 'b', 0x02, 0x00, 0x50, 'X', 'Y', 'Z', '1', '2'};
    uint8_t out[32];
    int n = scr_lz4_decompress(blk, sizeof blk, out, sizeof out);
    CHECK(n == 13 && memcmp(out, "ababababXYZ12", 13) == 0);
    CHECK(scr_lz4_decompress(blk, sizeof blk, out, 12) == -1);         /* output overflow */
    CHECK(scr_lz4_decompress(blk, 4, out, sizeof out) == -1);          /* truncated */
    {
        const uint8_t bad_off[] = {0x12, 'a', 0x05, 0x00, 0x00};       /* offset beyond output */
        CHECK(scr_lz4_decompress(bad_off, sizeof bad_off, out, sizeof out) == -1);
    }
    {
        /* long literal run (15 + 5 = 20) */
        uint8_t blk2[1 + 1 + 20];
        int i;
        blk2[0] = 0xF0; blk2[1] = 5;
        for (i = 0; i < 20; i++) blk2[2 + i] = (uint8_t)i;
        CHECK(scr_lz4_decompress(blk2, sizeof blk2, out, sizeof out) == 20 && out[19] == 19);
    }
}

static void test_fuzz(void) {
    /* random garbage must never crash (ASan) */
    static uint8_t msg[4096];
    scr_decoder_t d;
    unsigned s = 12345;
    int it, i;
    scr_dec_init(&d, canvas, SCR_W);
    for (it = 0; it < 20000; it++) {
        uint32_t len = (s = s * 1103515245u + 12345u) % sizeof msg;
        for (i = 0; i < (int)len; i++) msg[i] = (uint8_t)((s = s * 1103515245u + 12345u) >> 16);
        if (len >= 16) { msg[8] = (uint8_t)(it & 1); msg[12] = (uint8_t)(len & 0xFF); msg[13] = msg[14] = msg[15] = 0; }
        scr_dec_chunk(&d, msg, len, scratch, sizeof scratch);
        scr_lz4_decompress(msg, len, scratch, (uint32_t)(s % sizeof scratch));
    }
    CHECK(1);
}

int main(void) {
    test_raw_and_solid();
    test_errors_and_gaps();
    test_lz4();
    test_fuzz();
    if (fails) { printf("%d check(s) failed\n", fails); return 1; }
    printf("scr_codec host tests: OK\n");
    return 0;
}
