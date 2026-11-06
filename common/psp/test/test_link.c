/* Host unit tests for psp_link.h + link.c + io_pipe.c. Build/run: make -C common/psp/test */
#include <stdio.h>
#include <stdlib.h>
#include "../io_mailbox.h"
#include "../io_pipe.h"
#include "../link.h"

static int fails = 0;
#define CHECK(c)                                                         \
    do {                                                                 \
        if (!(c)) {                                                      \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
            fails++;                                                     \
        }                                                                \
    } while (0)

static void hex(const uint8_t *d, size_t n) {
    size_t i;
    for (i = 0; i < n; i++) printf("%02x", d[i]);
    printf("\n");
}

static void test_crc(void) {
    CHECK(psp_link_crc16((const uint8_t *)"123456789", 9) == 0x29B1); /* CCITT-FALSE check value */
}

static void test_roundtrip_bytewise(void) {
    uint8_t frame[64], pbuf[64];
    psp_link_parser_t p;
    psp_link_frame_t f;
    size_t n = psp_link_encode(frame, sizeof frame, 0x42, 0x01, 0x1234, "hello", 5), i, used;
    int got = 0;
    CHECK(n == 5 + PSP_LINK_OVERHEAD);
    psp_link_parser_init(&p, pbuf, sizeof pbuf);
    for (i = 0; i < n; i++) {
        if (psp_link_parser_feed(&p, frame + i, 1, &used, &f)) {
            got++;
            CHECK(i == n - 1);
        }
    }
    CHECK(got == 1);
    CHECK(f.type == 0x42 && f.flags == 0x01 && f.seq == 0x1234 && f.len == 5);
    CHECK(memcmp(f.payload, "hello", 5) == 0);
}

static void test_junk_crc_oversize(void) {
    uint8_t stream[256], pbuf[16];
    size_t n = 0, off = 0, used;
    psp_link_parser_t p;
    psp_link_frame_t f;
    int got = 0;
    uint8_t types[8];
    stream[n++] = 0x00;
    stream[n++] = 'P'; /* fake magic start */
    stream[n++] = 'P';
    n += psp_link_encode(stream + n, sizeof stream - n, 1, 0, 1, "a", 1); /* 'P' 'P' 'L'... must resync */
    {
        size_t k = psp_link_encode(stream + n, sizeof stream - n, 2, 0, 2, "bad", 3);
        stream[n + k - 1] ^= 0xFF; /* corrupt CRC */
        n += k;
    }
    n += psp_link_encode(stream + n, sizeof stream - n, 3, 0, 3, "0123456789abcdefXYZ", 19); /* > cap 16 */
    n += psp_link_encode(stream + n, sizeof stream - n, 4, 0, 4, NULL, 0);                    /* empty payload */
    psp_link_parser_init(&p, pbuf, sizeof pbuf);
    while (off < n) {
        if (psp_link_parser_feed(&p, stream + off, n - off, &used, &f)) types[got++] = f.type;
        off += used;
    }
    CHECK(got == 2);
    CHECK(types[0] == 1 && types[1] == 4);
    CHECK(p.crc_errors == 1);
    CHECK(p.oversize_frames == 1);
}

static void test_link_pipe(void) {
    static uint8_t a2b[4096], b2a[4096];
    static uint8_t rx_a[512], tx_a[512], ch_a[256], rx_b[512], tx_b[512], ch_b[256];
    psp_ring_t r1, r2;
    psp_pipe_end_t ea, eb;
    psp_link_t a, b;
    psp_link_frame_t f;
    uint8_t ping[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    psp_ring_init(&r1, a2b, sizeof a2b);
    psp_ring_init(&r2, b2a, sizeof b2a);
    ea.out = &r1;
    ea.in = &r2;
    eb.out = &r2;
    eb.in = &r1;
    psp_link_init(&a, psp_pipe_io(&ea), rx_a, sizeof rx_a, tx_a, sizeof tx_a, ch_a, sizeof ch_a);
    psp_link_init(&b, psp_pipe_io(&eb), rx_b, sizeof rx_b, tx_b, sizeof tx_b, ch_b, sizeof ch_b);
    b.app = 7;
    /* a = "Mac", b = "PSP" */
    CHECK(psp_link_send_hello(&a, PSP_LINK_T_HELLO, 0, "mac") == 0);
    CHECK(psp_link_poll(&b, 0, &f) == 1 && f.type == PSP_LINK_T_HELLO);
    CHECK(b.peer_hello && b.peer.max_payload == sizeof rx_a);
    CHECK(psp_link_poll(&a, 0, &f) == 1 && f.type == PSP_LINK_T_HELLO_ACK);
    CHECK(a.peer.app == 7 && a.peer.role == PSP_LINK_ROLE_PSP);
    CHECK(psp_link_send(&a, PSP_LINK_T_PING, 0, ping, 8) == 0);
    CHECK(psp_link_poll(&b, 0, &f) == 1 && f.type == PSP_LINK_T_PING);
    CHECK(psp_link_poll(&a, 0, &f) == 1 && f.type == PSP_LINK_T_PONG && f.len == 8 && memcmp(f.payload, ping, 8) == 0);
    CHECK(psp_link_poll(&a, 0, &f) == 0);
    /* many frames in one read chunk, bigger than the chunk buffer */
    {
        int i, n = 0;
        for (i = 0; i < 20; i++) psp_link_log(&b, "0123456789abcdef0123456789");
        while (psp_link_poll(&a, 0, &f) == 1) {
            CHECK(f.type == PSP_LINK_T_LOG && f.len == 26);
            n++;
        }
        CHECK(n == 20);
    }
    CHECK(psp_link_send(&a, 0x50, 0, NULL, 600) == -1); /* too big for tx buffer */
}

static void test_mailbox(void) {
    static uint8_t mem[64 + 300 + 200] __attribute__((aligned(64)));
    static uint8_t rx[512], tx[512], ch[128];
    psp_mbox_t mb;
    psp_link_t l;
    psp_link_frame_t f;
    uint8_t buf[600], frame[64];
    uint32_t n, total = 0;
    int i;
    CHECK(psp_mbox_init(&mb, mem, sizeof mem, 300, 200) == 0);
    CHECK(memcmp(mem, PSP_MBOX_MAGIC, 16) == 0 && mb.hdr->m2p_cap == 300 && !psp_mbox_bridge_seen(&mb));
    psp_link_init(&l, psp_mbox_io(&mb), rx, sizeof rx, tx, sizeof tx, ch, sizeof ch);
    mb.write_timeout_us = 0;
    /* Mac -> PSP across the ring wrap, 30 frames of 17 bytes through a 300-byte ring */
    for (i = 0; i < 30; i++) {
        size_t fl = psp_link_encode(frame, sizeof frame, 0x77, 0, (uint16_t)i, "abcde", 5);
        CHECK(psp_mbox_peer_write(&mb, frame, (uint32_t)fl) == fl);
        CHECK(psp_link_poll(&l, 0, &f) == 1 && f.type == 0x77 && f.seq == i);
    }
    CHECK(psp_mbox_bridge_seen(&mb));
    /* PSP -> Mac: ring full -> write fails with timeout 0 */
    CHECK(psp_link_send(&l, 0x78, 0, buf, 150) == 0);
    CHECK(psp_link_send(&l, 0x78, 0, buf, 150) == -2);
    n = psp_mbox_peer_read(&mb, buf, sizeof buf);
    total += n;
    CHECK(total == 200); /* first frame + part of the second (stream is broken, that is expected) */
}

/* Golden vectors; the same frames are produced by common/python/pspmac/protocol.py (tests/test_golden.py). */
static void golden(void) {
    uint8_t out[64];
    size_t n;
    n = psp_link_encode(out, sizeof out, PSP_LINK_T_HELLO, 0, 0, "\x01\x00\x01\x00\x00\x10\x00\x00psp", 11);
    hex(out, n);
    n = psp_link_encode(out, sizeof out, PSP_LINK_T_PING, 0, 0xBEEF, "\x01\x02\x03\x04", 4);
    hex(out, n);
    n = psp_link_encode(out, sizeof out, PSP_LINK_T_BYE, PSP_LINK_F_LAST, 65535, NULL, 0);
    hex(out, n);
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--golden") == 0) {
        golden();
        return 0;
    }
    test_crc();
    test_roundtrip_bytewise();
    test_junk_crc_oversize();
    test_link_pipe();
    test_mailbox();
    if (fails) {
        fprintf(stderr, "%d check(s) failed\n", fails);
        return 1;
    }
    printf("test_link: all checks passed\n");
    return 0;
}
