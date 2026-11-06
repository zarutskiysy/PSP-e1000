#include "bot.h"

uint16_t bw_bot_buttons(const bw_console_t *c, uint32_t frame, uint32_t now_ms, uint32_t ping_ms) {
    if (frame % 2u) return 0; /* release frame */
    switch (c->phase) {
    case BW_PH_TITLE:
        return c->link_up && (frame % 60u) == 0 ? BW_B_START : 0;
    case BW_PH_OVER:
        return 0;
    case BW_PH_PLAY:
        if (c->pings_sent == 0 || now_ms - c->last_ping_ms >= ping_ms) return BW_B_CROSS;
        if (c->ncontacts && (frame % 240u) == 0) return BW_B_TRIANGLE;
        return 0;
    case BW_PH_HACK: {
        int i = c->hack_cursor;
        if (now_ms - c->hack_start_ms < 600u) return 0; /* "read" the wave first */
        if (c->hack_val[i] != c->hack_target[i]) return BW_B_UP;
        for (i = 0; i < c->hack_n; i++)
            if (c->hack_val[i] != c->hack_target[i]) return BW_B_RIGHT;
        return BW_B_CROSS;
    }
    default:
        return 0;
    }
}
