#include "link.h"

void psp_link_init(psp_link_t *l, psp_link_io_t io, uint8_t *rx_payload, uint32_t rx_payload_cap, uint8_t *tx,
                   uint32_t tx_cap, uint8_t *rx_chunk, uint32_t rx_chunk_cap) {
    memset(l, 0, sizeof(*l));
    l->io = io;
    psp_link_parser_init(&l->parser, rx_payload, rx_payload_cap);
    l->tx = tx;
    l->tx_cap = tx_cap;
    l->rx_chunk = rx_chunk;
    l->rx_chunk_cap = rx_chunk_cap;
    l->auto_pong = 1;
    l->name = "psp";
}

int psp_link_send(psp_link_t *l, uint8_t type, uint8_t flags, const void *payload, uint32_t len) {
    size_t n = psp_link_encode(l->tx, l->tx_cap, type, flags, l->seq, payload, len);
    int w;
    if (!n) return -1;
    w = l->io.write(l->io.ctx, l->tx, (int)n);
    if (w != (int)n) return -2;
    l->seq++;
    l->tx_frames++;
    return 0;
}

int psp_link_send_hello(psp_link_t *l, uint8_t type, uint8_t app, const char *name) {
    uint8_t buf[8 + 32];
    size_t nl = name ? strlen(name) : 0;
    if (nl > 32) nl = 32;
    psp_link_put_u16(buf, PSP_LINK_VERSION);
    buf[2] = PSP_LINK_ROLE_PSP;
    buf[3] = app;
    psp_link_put_u32(buf + 4, l->parser.cap);
    if (nl) memcpy(buf + 8, name, nl);
    return psp_link_send(l, type, 0, buf, (uint32_t)(8 + nl));
}

static void handle_auto(psp_link_t *l, const psp_link_frame_t *f) {
    if (f->type == PSP_LINK_T_HELLO || f->type == PSP_LINK_T_HELLO_ACK) {
        if (f->len >= 8) {
            l->peer.version = psp_link_get_u16(f->payload);
            l->peer.role = f->payload[2];
            l->peer.app = f->payload[3];
            l->peer.max_payload = psp_link_get_u32(f->payload + 4);
        }
        l->peer_hello = 1;
        if (f->type == PSP_LINK_T_HELLO) psp_link_send_hello(l, PSP_LINK_T_HELLO_ACK, l->app, l->name);
    } else if (f->type == PSP_LINK_T_PING && l->auto_pong) {
        /* The payload lives in the parser buffer, which send() does not touch. */
        psp_link_send(l, PSP_LINK_T_PONG, 0, f->payload, f->len);
    }
}

int psp_link_poll(psp_link_t *l, int timeout_us, psp_link_frame_t *out) {
    int first = 1;
    for (;;) {
        while (l->rx_off < l->rx_have) {
            size_t used = 0;
            int got = psp_link_parser_feed(&l->parser, l->rx_chunk + l->rx_off, l->rx_have - l->rx_off, &used, out);
            l->rx_off += (uint32_t)used;
            if (got) {
                l->rx_frames++;
                handle_auto(l, out);
                return 1;
            }
        }
        l->rx_off = l->rx_have = 0;
        if (!first && timeout_us == 0) return 0;
        {
            int r = l->io.read(l->io.ctx, l->rx_chunk, (int)l->rx_chunk_cap, first ? timeout_us : 0);
            if (r < 0) return r;
            if (r == 0) return 0;
            l->rx_have = (uint32_t)r;
        }
        first = 0;
    }
}

int psp_link_log(psp_link_t *l, const char *text) {
    return psp_link_send(l, PSP_LINK_T_LOG, 0, text, (uint32_t)strlen(text));
}
