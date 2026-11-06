/*
 * link.h — PSP-side link logic on top of psp_link.h, transport-agnostic plain C.
 *
 * Compiles for the PSP (psp-gcc) and for macOS (clang) so the logic is unit-tested on the Mac.
 * A transport is a pair of callbacks (psp_link_io_t):
 *   - common/psp/io_pipe.c       in-memory pipe (tests, emulator demo mode)
 *   - common/psp/io_posix_tcp.c  POSIX TCP (macOS host builds; run PSP logic against Mac code)
 *   - common/psp/usb/usb_io.c    real USB bulk via the pspmaclink.prx kernel module (PSP only)
 */
#ifndef PSP_LINK_LOGIC_H
#define PSP_LINK_LOGIC_H

#include "../protocol/psp_link.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    /* Write exactly len bytes (may block). Return len on success, <0 on error. */
    int (*write)(void *ctx, const void *buf, int len);
    /* Read up to len bytes, waiting at most timeout_us (0 = poll, <0 = forever).
     * Return bytes read (>0), 0 on timeout, <0 on error/disconnect. */
    int (*read)(void *ctx, void *buf, int len, int timeout_us);
    void *ctx;
} psp_link_io_t;

typedef struct {
    psp_link_io_t io;
    psp_link_parser_t parser;
    uint8_t *tx;        /* scratch buffer for outgoing frames */
    uint32_t tx_cap;
    uint8_t *rx_chunk;  /* raw read buffer */
    uint32_t rx_chunk_cap;
    uint32_t rx_have;   /* unparsed bytes in rx_chunk */
    uint32_t rx_off;
    uint16_t seq;
    int auto_pong;      /* answer PING with PONG inside poll() (default 1) */
    int peer_hello;     /* set when HELLO or HELLO_ACK has been received */
    uint8_t app;        /* app id sent in automatic HELLO_ACK (set after init) */
    const char *name;   /* name sent in automatic HELLO_ACK (default "psp") */
    psp_link_hello_t peer;
    uint32_t tx_frames, rx_frames;
} psp_link_t;

/* All buffers are caller-provided (no malloc). rx_payload_cap = max payload accepted. */
void psp_link_init(psp_link_t *l, psp_link_io_t io, uint8_t *rx_payload, uint32_t rx_payload_cap, uint8_t *tx,
                   uint32_t tx_cap, uint8_t *rx_chunk, uint32_t rx_chunk_cap);

/* Sends one frame. Returns 0 on success, <0 on error (-1 too big, -2 io error). */
int psp_link_send(psp_link_t *l, uint8_t type, uint8_t flags, const void *payload, uint32_t len);

/* Sends HELLO (role PSP) with app id and name. */
int psp_link_send_hello(psp_link_t *l, uint8_t type, uint8_t app, const char *name);

/* Waits up to timeout_us for one frame. Returns 1 and fills *out, 0 on timeout, <0 on io error.
 * PINGs are answered automatically (and still returned) when auto_pong is set.
 * A HELLO from the peer is answered with HELLO_ACK automatically (role PSP, l->app, l->name). */
int psp_link_poll(psp_link_t *l, int timeout_us, psp_link_frame_t *out);

/* Convenience: send a LOG frame with printf-free text. */
int psp_link_log(psp_link_t *l, const char *text);

#ifdef __cplusplus
}
#endif
#endif
