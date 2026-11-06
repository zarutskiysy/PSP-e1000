/* console.h — PSP side of Blackwater Ping: sonar scope + hacking console. Plain C (PSP + macOS).
 * Transport-agnostic: frames come in via bw_console_on_frame(), outgoing messages go through the
 * send callback. Rendering is separate (view.c). */
#ifndef BW_CONSOLE_H
#define BW_CONSOLE_H
#include <stdint.h>
#include "../proto_game.h"

enum { BW_PH_TITLE = 0, BW_PH_PLAY = 1, BW_PH_HACK = 2, BW_PH_OVER = 3 };

#define BW_MAX_CONTACTS 32
#define BW_LOG_LINES 6
#define BW_LOG_COLS 33
#define BW_HACK_MAX 6

#define BW_PING_COOLDOWN_MS 1500u
#define BW_LISTEN_COOLDOWN_MS 600u
#define BW_HACK_PENALTY_MS 3000u
#define BW_PILOT_PERIOD_MS 50u /* 20 Hz while the nub is deflected */

typedef void (*bw_send_fn)(void *ctx, uint8_t type, const uint8_t *payload, uint32_t len);

typedef struct {
    float wx, wy;        /* world position (computed from sub position at receipt) */
    uint16_t bearing, range;
    uint8_t kind, strength, ping_id, index, passive, marked;
    uint32_t t_ms;       /* receipt time */
} bw_contact_t;

typedef struct {
    int phase;
    int link_up;
    uint32_t now_ms;
    /* from the Mac */
    bw_game_start_t game;
    bw_sub_state_t sub;
    int have_sub;
    uint32_t sub_rx_ms;
    bw_contact_t contacts[BW_MAX_CONTACTS];
    int ncontacts;
    uint8_t last_active_ping;
    int outcome; /* 0 none, 1 win, 2 lose */
    uint32_t alert_until_ms;
    /* sonar */
    uint8_t next_ping_id;
    uint32_t last_ping_ms, last_listen_ms;
    int pings_sent, listens_sent, marks_sent, echoes_rx;
    /* hack puzzle: "phase lock" — match the target waveform with the D-pad */
    uint8_t hack_gate, hack_n, hack_cursor, hack_target[BW_HACK_MAX], hack_val[BW_HACK_MAX];
    uint32_t hack_start_ms, hack_deadline_ms;
    int hacks_ok, hacks_failed;
    /* input */
    uint16_t prev_buttons;
    int8_t last_ax, last_ay;
    uint32_t last_pilot_ms;
    /* text log (newest last) */
    char log[BW_LOG_LINES][BW_LOG_COLS + 1];
    /* outgoing */
    bw_send_fn send;
    void *send_ctx;
    uint32_t tx_msgs, rx_msgs;
} bw_console_t;

void bw_console_init(bw_console_t *c, bw_send_fn send, void *ctx);
void bw_console_set_link(bw_console_t *c, int up);
void bw_console_on_frame(bw_console_t *c, uint8_t type, const uint8_t *payload, uint32_t len);
/* buttons = BW_B_* bitmask, ax/ay = nub -127..127 (+y = down) */
void bw_console_tick(bw_console_t *c, uint32_t now_ms, uint16_t buttons, int8_t ax, int8_t ay);
void bw_console_log(bw_console_t *c, const char *text);
/* Generates the puzzle for a HACK_REQ (exposed for tests). */
void bw_hack_generate(uint32_t seed, uint8_t difficulty, uint8_t *n, uint8_t *target, uint8_t *start);
/* Bearing (u16) -> unit vector (x right, y down). */
void bw_bearing_vec(uint16_t bearing, float *dx, float *dy);
#endif
