#ifndef BW_DEMO_MAC_H
#define BW_DEMO_MAC_H
#include "../../common/psp/link.h"
#include "../proto_game.h"

typedef struct {
    psp_link_t link;
    uint8_t rx[512], tx[512], chunk[512];
    uint32_t now, t0, last_state, win_at, hack_retry_at, games;
    int running, hack_sent, gate_open;
    float x, y, cre_x, cre_y;
    uint16_t heading;
    uint8_t hull, battery, noise;
} demo_mac_t;

void demo_mac_init(demo_mac_t *d, psp_link_io_t io);
void demo_mac_step(demo_mac_t *d, uint32_t now_ms);
#endif
