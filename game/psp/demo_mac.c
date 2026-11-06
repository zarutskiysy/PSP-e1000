/* demo_mac.c — a tiny scripted "Mac" living in the same process (pipe io). Used when no real link
 * exists (PPSSPP without the bridge, or a PSP without the USB modules) so the console is playable
 * and screenshot-able on its own. It is NOT the real game: the real world simulation is the Mac
 * game (game/mac/blackwater.py). */
#include "demo_mac.h"
#include <math.h>
#include <string.h>

static const float mines[][2] = {{140, 260}, {-120, 420}, {60, 610}, {-60, 150}, {200, 520}, {-210, 330}};

static void send(demo_mac_t *d, uint8_t type, const uint8_t *p, uint32_t n) {
    psp_link_send(&d->link, type, 0, p, n);
}

static void event(demo_mac_t *d, uint8_t code, uint16_t arg) {
    uint8_t p[BW_SZ_EVENT];
    bw_event_t e;
    e.code = code;
    e.arg = arg;
    send(d, BW_T_EVENT, p, bw_pack_event(p, &e));
}

static uint16_t bearing_to(float dx, float dy) {
    float a = atan2f(dx, -dy);
    if (a < 0) a += 6.2831853f;
    return (uint16_t)(a * (65536.0f / 6.2831853f));
}

static void start(demo_mac_t *d) {
    uint8_t p[BW_SZ_GAME_START];
    bw_game_start_t g;
    g.level = 1; g.mode = BW_MODE_COOP; g.seed = 0xB1ACu + d->games; g.max_range = 700;
    send(d, BW_T_GAME_START, p, bw_pack_game_start(p, &g));
    d->running = 1;
    d->t0 = d->now;
    d->hull = 100; d->battery = 100; d->noise = 0;
    d->hack_sent = 0; d->gate_open = 0; d->win_at = 0;
    d->games++;
}

static void echo(demo_mac_t *d, const bw_ping_cmd_t *pc) {
    bw_echo_t e;
    uint8_t p[BW_SZ_ECHO_HDR + BW_ECHO_MAX * BW_SZ_CONTACT];
    unsigned i;
    float cx = d->cre_x - d->x, cy = d->cre_y - d->y;
    memset(&e, 0, sizeof e);
    e.ping_id = pc->ping_id;
    e.mode = pc->mode;
    if (pc->mode == BW_PING_ACTIVE) {
        for (i = 0; i < sizeof mines / sizeof mines[0]; i++) {
            float dx = mines[i][0] - d->x, dy = mines[i][1] - d->y, r = sqrtf(dx * dx + dy * dy);
            if (r > 700) continue;
            e.c[e.n].bearing = bearing_to(dx, dy); e.c[e.n].range = (uint16_t)r;
            e.c[e.n].kind = BW_K_MINE; e.c[e.n].strength = 200; e.n++;
        }
        if (!d->gate_open) {
            float dy = 700 - d->y;
            e.c[e.n].bearing = bearing_to(-d->x, dy); e.c[e.n].range = (uint16_t)sqrtf(d->x * d->x + dy * dy);
            e.c[e.n].kind = BW_K_GATE; e.c[e.n].strength = 255; e.n++;
        }
        d->noise = 100;
        d->battery = d->battery > 3 ? d->battery - 3 : 0;
    }
    if (sqrtf(cx * cx + cy * cy) < 900) {
        e.c[e.n].bearing = bearing_to(cx, cy);
        e.c[e.n].range = pc->mode == BW_PING_ACTIVE ? (uint16_t)sqrtf(cx * cx + cy * cy) : 0;
        e.c[e.n].kind = BW_K_CREATURE; e.c[e.n].strength = 180; e.n++;
    }
    send(d, BW_T_ECHO, p, bw_pack_echo(p, &e));
}

void demo_mac_init(demo_mac_t *d, psp_link_io_t io) {
    memset(d, 0, sizeof *d);
    psp_link_init(&d->link, io, d->rx, sizeof d->rx, d->tx, sizeof d->tx, d->chunk, sizeof d->chunk);
    d->link.name = "demo_mac";
    psp_link_send_hello(&d->link, PSP_LINK_T_HELLO, BW_APP_ID, "demo_mac");
}

void demo_mac_step(demo_mac_t *d, uint32_t now_ms) {
    psp_link_frame_t f;
    float t;
    d->now = now_ms;
    while (psp_link_poll(&d->link, 0, &f) == 1) {
        if (f.type == BW_T_READY) start(d);
        else if (f.type == BW_T_PING_CMD && f.len >= BW_SZ_PING_CMD && d->running) {
            bw_ping_cmd_t pc;
            pc.ping_id = f.payload[0]; pc.mode = f.payload[1];
            echo(d, &pc);
        } else if (f.type == BW_T_HACK_RESULT && f.len >= BW_SZ_HACK_RESULT) {
            if (f.payload[1]) { d->gate_open = 1; event(d, BW_EV_GATE_OPEN, f.payload[0]); d->win_at = now_ms + 15000; }
            else { d->hack_sent = 0; d->hack_retry_at = now_ms + 3000; event(d, BW_EV_HACK_FAIL, 0); d->noise = 100; }
        } else if (f.type == BW_T_MARK) {
            event(d, BW_EV_MARKED, f.payload[1]);
        }
    }
    if (!d->running) { /* keep the link alive on the title / game-over screens */
        if (now_ms - d->last_state >= 500u) {
            d->last_state = now_ms;
            psp_link_send(&d->link, PSP_LINK_T_PING, 0, "demo", 4);
        }
        return;
    }
    t = (float)(now_ms - d->t0) / 1000.0f;
    /* scripted path: swing down the shaft towards the gate at y=700 */
    d->x = 120.0f * sinf(t * 0.35f);
    d->y = d->gate_open ? 690.0f + (t - 20.0f) * 20.0f : (t * 30.0f < 690.0f ? t * 30.0f : 690.0f);
    d->heading = bearing_to(0.35f * 120.0f * cosf(t * 0.35f), 30.0f);
    d->cre_x = 260.0f * cosf(t * 0.2f);
    d->cre_y = 450.0f + 120.0f * sinf(t * 0.27f);
    if (d->noise > 0) d->noise--;
    if (now_ms - d->last_state >= 66u) {
        uint8_t p[BW_SZ_SUB_STATE];
        bw_sub_state_t s;
        d->last_state = now_ms;
        s.tick = (uint16_t)(now_ms / 33u); s.x = (int16_t)d->x; s.y = (int16_t)d->y; s.heading = d->heading;
        s.speed = 30; s.hull = d->hull; s.battery = d->battery; s.noise = d->noise;
        s.flags = (uint8_t)(BW_SF_RUNNING | (d->y >= 690.0f && !d->gate_open ? BW_SF_AT_GATE : 0));
        s.gates_open = (uint8_t)d->gate_open;
        send(d, BW_T_SUB_STATE, p, bw_pack_sub_state(p, &s));
    }
    if (!d->gate_open && !d->hack_sent && d->y >= 690.0f && (int32_t)(now_ms - d->hack_retry_at) >= 0) {
        uint8_t p[BW_SZ_HACK_REQ];
        bw_hack_req_t h;
        h.gate_id = 1; h.puzzle = 0; h.difficulty = 1; h.seed = 0xC0DE0000u + now_ms; h.time_limit_ds = 200;
        send(d, BW_T_HACK_REQ, p, bw_pack_hack_req(p, &h));
        d->hack_sent = 1;
    }
    if (d->win_at && (int32_t)(now_ms - d->win_at) >= 0) {
        event(d, BW_EV_WIN, 0);
        d->running = 0;
        d->win_at = 0;
    }
}
