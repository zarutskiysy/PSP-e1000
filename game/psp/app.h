/* app.h — glue: link (any io) + console + optional in-process demo Mac. Plain C, PSP + macOS. */
#ifndef BW_APP_H
#define BW_APP_H
#include "../../common/psp/io_pipe.h"
#include "../../common/psp/link.h"
#include "console.h"
#include "demo_mac.h"

typedef struct {
    psp_link_t link;
    bw_console_t con;
    uint8_t rx[1024], tx[1024], chunk[2048];
    const char *io_name;
    int io_dead;           /* io returned an error: stop using it */
    uint32_t last_rx_ms, last_hello_ms, now_ms;
    /* optional: returns 0 while nobody can be listening (HELLOs are held back) */
    int (*peer_present)(void *ctx);
    void *peer_ctx;
    /* demo mode */
    int demo;
    demo_mac_t demo_mac;
    psp_ring_t r1, r2;
    uint8_t b1[4096], b2[4096];
    psp_pipe_end_t ea, eb;
} bw_app_t;

void bw_app_init(bw_app_t *a, psp_link_io_t io, const char *io_name);
/* Demo: console talks to demo_mac.c over an in-memory pipe. */
void bw_app_init_demo(bw_app_t *a);
void bw_app_step(bw_app_t *a, uint32_t now_ms, uint16_t buttons, int8_t ax, int8_t ay);
#endif
