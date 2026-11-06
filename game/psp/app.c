#include "app.h"
#include <string.h>

#define LINK_TIMEOUT_MS 2500u
#define HELLO_PERIOD_MS 1000u

static void app_send(void *ctx, uint8_t type, const uint8_t *p, uint32_t n) {
    bw_app_t *a = (bw_app_t *)ctx;
    if (a->io_dead) return;
    if (psp_link_send(&a->link, type, 0, p, n) == -2) a->io_dead = 1;
}

void bw_app_init(bw_app_t *a, psp_link_io_t io, const char *io_name) {
    memset(a, 0, sizeof *a);
    psp_link_init(&a->link, io, a->rx, sizeof a->rx, a->tx, sizeof a->tx, a->chunk, sizeof a->chunk);
    a->link.app = BW_APP_ID;
    a->link.name = "blackwater_psp";
    a->io_name = io_name;
    bw_console_init(&a->con, app_send, a);
    a->last_hello_ms = (uint32_t)-HELLO_PERIOD_MS;
}

void bw_app_init_demo(bw_app_t *a) {
    psp_ring_t *r1, *r2;
    memset(a, 0, sizeof *a);
    r1 = &a->r1;
    r2 = &a->r2;
    psp_ring_init(r1, a->b1, sizeof a->b1);
    psp_ring_init(r2, a->b2, sizeof a->b2);
    a->ea.out = r1; a->ea.in = r2; /* demo Mac end */
    a->eb.out = r2; a->eb.in = r1; /* console end */
    {
        demo_mac_t *d = &a->demo_mac;
        demo_mac_init(d, psp_pipe_io(&a->ea));
    }
    /* bw_app_init would wipe the struct: init the link part by hand */
    psp_link_init(&a->link, psp_pipe_io(&a->eb), a->rx, sizeof a->rx, a->tx, sizeof a->tx, a->chunk, sizeof a->chunk);
    a->link.app = BW_APP_ID;
    a->link.name = "blackwater_psp";
    a->io_name = "DEMO";
    a->demo = 1;
    bw_console_init(&a->con, app_send, a);
    a->last_hello_ms = (uint32_t)-HELLO_PERIOD_MS;
}

void bw_app_step(bw_app_t *a, uint32_t now_ms, uint16_t buttons, int8_t ax, int8_t ay) {
    psp_link_frame_t f;
    int r, budget = 64;
    a->now_ms = now_ms;
    a->con.now_ms = now_ms;
    if (a->demo) demo_mac_step(&a->demo_mac, now_ms);
    while (!a->io_dead && budget-- > 0 && (r = psp_link_poll(&a->link, 0, &f)) != 0) {
        if (r < 0) { a->io_dead = 1; break; }
        a->last_rx_ms = now_ms;
        bw_console_set_link(&a->con, 1);
        bw_console_on_frame(&a->con, f.type, f.payload, f.len);
    }
    if (a->con.link_up && now_ms - a->last_rx_ms > LINK_TIMEOUT_MS) {
        bw_console_set_link(&a->con, 0);
        a->link.peer_hello = 0;
    }
    if (!a->con.link_up && !a->io_dead && now_ms - a->last_hello_ms >= HELLO_PERIOD_MS) {
        a->last_hello_ms = now_ms;
        if (psp_link_send_hello(&a->link, PSP_LINK_T_HELLO, BW_APP_ID, "blackwater_psp") == -2) a->io_dead = 1;
    }
    bw_console_tick(&a->con, now_ms, buttons, ax, ay);
}
