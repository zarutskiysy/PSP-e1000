#include "console.h"
#include <math.h>
#include <string.h>

static void send_msg(bw_console_t *c, uint8_t type, const uint8_t *p, uint32_t n) {
    if (c->send) c->send(c->send_ctx, type, p, n);
    c->tx_msgs++;
}

void bw_bearing_vec(uint16_t bearing, float *dx, float *dy) {
    float a = (float)bearing * (6.2831853f / 65536.0f);
    *dx = sinf(a);
    *dy = -cosf(a);
}

void bw_console_log(bw_console_t *c, const char *text) {
    int i;
    for (i = 0; i < BW_LOG_LINES - 1; i++) memcpy(c->log[i], c->log[i + 1], sizeof c->log[i]);
    for (i = 0; i < BW_LOG_COLS && text[i]; i++) c->log[BW_LOG_LINES - 1][i] = text[i];
    c->log[BW_LOG_LINES - 1][i] = 0;
}

/* Small integer formatting without printf (keeps the PSP binary lean and the code freestanding). */
static char *put_uint(char *p, unsigned v) {
    char tmp[12];
    int n = 0;
    do { tmp[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) *p++ = tmp[--n];
    *p = 0;
    return p;
}
static char *put_str(char *p, const char *s) {
    while (*s) *p++ = *s++;
    *p = 0;
    return p;
}

void bw_console_init(bw_console_t *c, bw_send_fn send, void *ctx) {
    memset(c, 0, sizeof *c);
    c->send = send;
    c->send_ctx = ctx;
    c->phase = BW_PH_TITLE;
    c->game.max_range = 700;
    c->next_ping_id = 1;
    bw_console_log(c, "BLACKWATER PING CONSOLE V1");
    bw_console_log(c, "WAITING FOR THE SUB...");
}

void bw_console_set_link(bw_console_t *c, int up) {
    if (up && !c->link_up) bw_console_log(c, "LINK UP");
    if (!up && c->link_up) bw_console_log(c, "LINK LOST");
    c->link_up = up;
}

void bw_hack_generate(uint32_t seed, uint8_t difficulty, uint8_t *n, uint8_t *target, uint8_t *start) {
    uint32_t s = seed, i;
    uint8_t k = (uint8_t)(3 + difficulty);
    if (k > BW_HACK_MAX) k = BW_HACK_MAX;
    *n = k;
    for (i = 0; i < k; i++) {
        target[i] = (uint8_t)(bw_rng_next(&s) % 8u);
        start[i] = (uint8_t)((target[i] + 1 + bw_rng_next(&s) % 7u) % 8u); /* never already solved */
    }
}

static void add_echo(bw_console_t *c, const bw_echo_t *e) {
    int i;
    char line[48], *p;
    /* an active echo replaces the previous picture; passive bearings are appended */
    if (e->mode == BW_PING_ACTIVE) {
        c->ncontacts = 0;
        c->last_active_ping = e->ping_id;
    } else {
        int j = 0;
        for (i = 0; i < c->ncontacts; i++)
            if (!c->contacts[i].passive) c->contacts[j++] = c->contacts[i];
        c->ncontacts = j;
    }
    for (i = 0; i < e->n && c->ncontacts < BW_MAX_CONTACTS; i++) {
        bw_contact_t *k = &c->contacts[c->ncontacts++];
        float dx, dy;
        bw_bearing_vec(e->c[i].bearing, &dx, &dy);
        memset(k, 0, sizeof *k);
        k->bearing = e->c[i].bearing;
        k->range = e->c[i].range;
        k->kind = e->c[i].kind;
        k->strength = e->c[i].strength;
        k->ping_id = e->ping_id;
        k->index = (uint8_t)i;
        k->passive = e->mode == BW_PING_PASSIVE;
        k->wx = (float)c->sub.x + dx * (float)k->range;
        k->wy = (float)c->sub.y + dy * (float)k->range;
        k->t_ms = c->now_ms;
    }
    c->echoes_rx++;
    p = put_str(line, e->mode == BW_PING_ACTIVE ? "ECHO #" : "LISTEN #");
    p = put_uint(p, e->ping_id);
    p = put_str(p, ": ");
    p = put_uint(p, e->n);
    put_str(p, e->mode == BW_PING_ACTIVE ? " CONTACTS" : " BEARINGS");
    bw_console_log(c, line);
}

static void start_hack(bw_console_t *c, const bw_hack_req_t *h) {
    char line[48], *p;
    c->phase = BW_PH_HACK;
    c->hack_gate = h->gate_id;
    bw_hack_generate(h->seed, h->difficulty, &c->hack_n, c->hack_target, c->hack_val);
    c->hack_cursor = 0;
    c->hack_start_ms = c->now_ms;
    c->hack_deadline_ms = c->now_ms + (uint32_t)h->time_limit_ds * 100u;
    p = put_str(line, "GATE ");
    p = put_uint(p, h->gate_id);
    put_str(p, " LOCKED: MATCH THE WAVE");
    bw_console_log(c, line);
}

static void finish_hack(bw_console_t *c, int ok) {
    uint8_t p[BW_SZ_HACK_RESULT];
    bw_hack_result_t r;
    uint32_t el = (c->now_ms - c->hack_start_ms) / 100u;
    r.gate_id = c->hack_gate;
    r.ok = (uint8_t)(ok ? 1 : 0);
    r.elapsed_ds = (uint16_t)(el > 65535u ? 65535u : el);
    send_msg(c, BW_T_HACK_RESULT, p, bw_pack_hack_result(p, &r));
    if (ok) c->hacks_ok++; else c->hacks_failed++;
    bw_console_log(c, ok ? "LOCK OPEN" : "HACK FAILED - NOISE!");
    c->phase = BW_PH_PLAY;
}

void bw_console_on_frame(bw_console_t *c, uint8_t type, const uint8_t *payload, uint32_t len) {
    c->rx_msgs++;
    switch (type) {
    case PSP_LINK_T_HELLO:
    case PSP_LINK_T_HELLO_ACK:
        bw_console_set_link(c, 1);
        break;
    case BW_T_GAME_START: {
        bw_game_start_t g;
        if (bw_unpack_game_start(payload, len, &g)) break;
        c->game = g;
        if (!c->game.max_range) c->game.max_range = 700;
        c->phase = BW_PH_PLAY;
        c->ncontacts = 0;
        c->outcome = 0;
        c->have_sub = 0;
        bw_console_log(c, g.mode == BW_MODE_SOLO ? "DIVE! SOLO: NUB STEERS" : "DIVE! CO-OP");
        break;
    }
    case BW_T_SUB_STATE:
        if (!bw_unpack_sub_state(payload, len, &c->sub)) {
            c->have_sub = 1;
            c->sub_rx_ms = c->now_ms;
        }
        break;
    case BW_T_ECHO: {
        bw_echo_t e;
        if (!bw_unpack_echo(payload, len, &e)) add_echo(c, &e);
        break;
    }
    case BW_T_HACK_REQ: {
        bw_hack_req_t h;
        if (bw_unpack_hack_req(payload, len, &h)) break;
        if (c->phase == BW_PH_HACK && h.gate_id == c->hack_gate) break; /* retransmit: keep puzzle */
        start_hack(c, &h);
        break;
    }
    case BW_T_EVENT: {
        bw_event_t ev;
        if (bw_unpack_event(payload, len, &ev)) break;
        switch (ev.code) {
        case BW_EV_DAMAGE: bw_console_log(c, "HULL DAMAGE!"); c->alert_until_ms = c->now_ms + 700; break;
        case BW_EV_CREATURE_NEAR: bw_console_log(c, "SOMETHING IS CLOSE..."); c->alert_until_ms = c->now_ms + 1200; break;
        case BW_EV_GATE_OPEN: bw_console_log(c, "BULKHEAD OPEN"); break;
        case BW_EV_BATTERY_LOW: bw_console_log(c, "BATTERY LOW"); break;
        case BW_EV_HACK_FAIL: bw_console_log(c, "LOCK ALARM: IT HEARD US"); c->alert_until_ms = c->now_ms + 1000; break;
        case BW_EV_MARKED: bw_console_log(c, "BUOY DROPPED"); break;
        case BW_EV_WIN: c->phase = BW_PH_OVER; c->outcome = 1; bw_console_log(c, "SURFACED: SALVAGE SAFE"); break;
        case BW_EV_LOSE: c->phase = BW_PH_OVER; c->outcome = 2; bw_console_log(c, "SIGNAL LOST"); break;
        default: break;
        }
        break;
    }
    default:
        break;
    }
}

static void do_ping(bw_console_t *c, uint8_t mode) {
    uint8_t p[BW_SZ_PING_CMD];
    bw_ping_cmd_t m;
    m.ping_id = c->next_ping_id++;
    if (!c->next_ping_id) c->next_ping_id = 1;
    m.mode = mode;
    m.bearing = 0;
    m.width = 0xFFFF; /* full circle */
    send_msg(c, BW_T_PING_CMD, p, bw_pack_ping_cmd(p, &m));
    if (mode == BW_PING_ACTIVE) { c->last_ping_ms = c->now_ms; c->pings_sent++; }
    else { c->last_listen_ms = c->now_ms; c->listens_sent++; }
}

static void do_mark(bw_console_t *c) {
    int i, best = -1;
    float bd = 1e9f;
    for (i = 0; i < c->ncontacts; i++) {
        bw_contact_t *k = &c->contacts[i];
        float dx, dy, d;
        if (k->passive || k->marked || (k->kind != BW_K_MINE && k->kind != BW_K_CREATURE)) continue;
        dx = k->wx - (float)c->sub.x;
        dy = k->wy - (float)c->sub.y;
        d = dx * dx + dy * dy;
        if (d < bd) { bd = d; best = i; }
    }
    if (best < 0) { bw_console_log(c, "NOTHING TO MARK - PING FIRST"); return; }
    {
        uint8_t p[BW_SZ_MARK];
        bw_mark_t m;
        m.ping_id = c->contacts[best].ping_id;
        m.index = c->contacts[best].index;
        m.tag = c->contacts[best].kind;
        c->contacts[best].marked = 1;
        send_msg(c, BW_T_MARK, p, bw_pack_mark(p, &m));
        c->marks_sent++;
        bw_console_log(c, c->contacts[best].kind == BW_K_MINE ? "MARKED MINE" : "MARKED CREATURE");
    }
}

static void hack_input(bw_console_t *c, uint16_t pressed) {
    if (pressed & BW_B_LEFT) c->hack_cursor = (uint8_t)(c->hack_cursor ? c->hack_cursor - 1 : c->hack_n - 1);
    if (pressed & BW_B_RIGHT) c->hack_cursor = (uint8_t)((c->hack_cursor + 1) % c->hack_n);
    if (pressed & BW_B_UP) c->hack_val[c->hack_cursor] = (uint8_t)((c->hack_val[c->hack_cursor] + 1) % 8u);
    if (pressed & BW_B_DOWN) c->hack_val[c->hack_cursor] = (uint8_t)((c->hack_val[c->hack_cursor] + 7) % 8u);
    if (pressed & BW_B_CIRCLE) { finish_hack(c, 0); return; }
    if (pressed & BW_B_CROSS) {
        if (!memcmp(c->hack_val, c->hack_target, c->hack_n)) {
            finish_hack(c, 1);
        } else {
            c->hack_deadline_ms = c->hack_deadline_ms > c->now_ms + BW_HACK_PENALTY_MS
                                      ? c->hack_deadline_ms - BW_HACK_PENALTY_MS
                                      : c->now_ms;
            bw_console_log(c, "MISMATCH: -3 S");
        }
    }
}

void bw_console_tick(bw_console_t *c, uint32_t now_ms, uint16_t buttons, int8_t ax, int8_t ay) {
    uint16_t pressed = (uint16_t)(buttons & ~c->prev_buttons);
    c->now_ms = now_ms;
    c->prev_buttons = buttons;

    if (pressed & BW_B_START) {
        if (c->phase == BW_PH_TITLE || c->phase == BW_PH_OVER) {
            uint8_t p[BW_SZ_READY];
            send_msg(c, BW_T_READY, p, bw_pack_ready(p, 1));
            bw_console_log(c, "READY SENT");
        }
    }
    if (c->phase == BW_PH_PLAY) {
        if ((pressed & BW_B_CROSS) && (c->pings_sent == 0 || now_ms - c->last_ping_ms >= BW_PING_COOLDOWN_MS))
            do_ping(c, BW_PING_ACTIVE);
        if ((pressed & BW_B_SQUARE) &&
            (c->listens_sent == 0 || now_ms - c->last_listen_ms >= BW_LISTEN_COOLDOWN_MS))
            do_ping(c, BW_PING_PASSIVE);
        if (pressed & BW_B_TRIANGLE) do_mark(c);
    } else if (c->phase == BW_PH_HACK) {
        hack_input(c, pressed);
        if (c->phase == BW_PH_HACK && (int32_t)(now_ms - c->hack_deadline_ms) >= 0) finish_hack(c, 0);
    }
    /* nub -> PILOT (solo mode on the Mac side uses it; co-op ignores it) */
    if (c->phase == BW_PH_PLAY || c->phase == BW_PH_HACK) {
        int dz = 24, active = (ax > dz || ax < -dz || ay > dz || ay < -dz);
        int8_t sx = active ? ax : 0, sy = active ? ay : 0;
        int changed = sx != c->last_ax || sy != c->last_ay;
        if ((active && now_ms - c->last_pilot_ms >= BW_PILOT_PERIOD_MS) || (!active && changed)) {
            uint8_t p[BW_SZ_PILOT];
            bw_pilot_t m;
            m.ax = sx; m.ay = sy; m.buttons = buttons;
            send_msg(c, BW_T_PILOT, p, bw_pack_pilot(p, &m));
            c->last_ax = sx; c->last_ay = sy;
            c->last_pilot_ms = now_ms;
        }
    }
}
