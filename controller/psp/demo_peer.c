#include "demo_peer.h"

#include <pspthreadman.h>
#include <stdio.h>
#include <string.h>

#include "../../common/psp/io_pipe.h"
#include "../proto_controller.h"

static const char *k_labels[] = {"Mission Ctrl", "Play/Pause", "Screenshot", "Next track", "Cmd+Tab", "Downloads"};
#define N_LABELS (sizeof k_labels / sizeof k_labels[0])

static uint8_t a2b[4096], b2a[4096];
static psp_ring_t r_psp_to_mac, r_mac_to_psp;
static psp_pipe_end_t end_psp, end_mac;
static psp_link_t mac;
static uint8_t mac_rx[512], mac_tx[512], mac_chunk[1024];
static unsigned inputs_window, last_status_us;

psp_link_io_t demo_peer_open(void) {
    psp_ring_init(&r_psp_to_mac, a2b, sizeof a2b);
    psp_ring_init(&r_mac_to_psp, b2a, sizeof b2a);
    end_psp.out = &r_psp_to_mac;
    end_psp.in = &r_mac_to_psp;
    end_mac.out = &r_mac_to_psp;
    end_mac.in = &r_psp_to_mac;
    psp_link_init(&mac, psp_pipe_io(&end_mac), mac_rx, sizeof mac_rx, mac_tx, sizeof mac_tx, mac_chunk,
                  sizeof mac_chunk);
    mac.name = "demo-mac";
    return psp_pipe_io(&end_psp);
}

static void send_config(void) {
    uint8_t p[CTRL_WHEEL_CONFIG_SIZE];
    unsigned i;
    memset(p, 0, sizeof p);
    p[0] = N_LABELS;
    p[1] = 1;
    for (i = 0; i < N_LABELS; i++) strncpy((char *)p + 4 + i * CTRL_LABEL_LEN, k_labels[i], CTRL_LABEL_LEN - 1);
    psp_link_send(&mac, CTRL_T_WHEEL_CONFIG, 0, p, sizeof p);
}

void demo_peer_step(void) {
    psp_link_frame_t f;
    unsigned now = sceKernelGetSystemTimeLow();
    while (psp_link_poll(&mac, 0, &f) == 1) {
        if (f.type == PSP_LINK_T_HELLO || f.type == CTRL_T_CONFIG_REQ) {
            send_config();
        } else if (f.type == CTRL_T_INPUT_STATE) {
            inputs_window++;
        } else if (f.type == CTRL_T_WHEEL_FIRE && f.len >= 1) {
            uint8_t p[CTRL_ACTION_RESULT_SIZE];
            unsigned s = f.payload[0];
            memset(p, 0, sizeof p);
            p[0] = (uint8_t)s;
            p[1] = s < N_LABELS;
            snprintf((char *)p + 4, CTRL_RESULT_TEXT_LEN, "demo: %s (no Mac attached)",
                     s < N_LABELS ? k_labels[s] : "?");
            psp_link_send(&mac, CTRL_T_ACTION_RESULT, 0, p, sizeof p);
        }
    }
    if (now - last_status_us >= 1000000u) {
        uint8_t p[CTRL_MAC_STATUS_SIZE];
        memset(p, 0, sizeof p);
        psp_link_put_u16(p + 8, (uint16_t)(inputs_window * 1000000u / (now - last_status_us + 1)));
        p[10] = 1; /* dry run */
        if (last_status_us) psp_link_send(&mac, CTRL_T_MAC_STATUS, 0, p, sizeof p);
        inputs_window = 0;
        last_status_us = now;
    }
}
