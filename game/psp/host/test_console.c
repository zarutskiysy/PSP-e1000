/* Host unit tests for the PSP console (plain C, same sources as the EBOOT). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../../common/psp/io_pipe.h"
#include "../app.h"
#include "../bot.h"
#include "../view.h"

static int fails = 0;
#define CHECK(cond) do { if (!(cond)) { fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); fails++; } } while (0)

typedef struct { uint8_t type; uint8_t p[256]; uint32_t n; } msg_t;
static msg_t sent[64];
static int nsent;
static void cap_send(void *ctx, uint8_t type, const uint8_t *p, uint32_t n) {
    (void)ctx;
    if (nsent < 64) { sent[nsent].type = type; memcpy(sent[nsent].p, p, n); sent[nsent].n = n; nsent++; }
}
static const msg_t *last_of(uint8_t type) {
    int i;
    for (i = nsent - 1; i >= 0; i--) if (sent[i].type == type) return &sent[i];
    return NULL;
}

static void test_golden(void) {
    uint8_t p[256];
    bw_sub_state_t s = {0x1234, -5, 700, 0x4000, 30, 100, 90, 7, 9, 1}, s2;
    bw_echo_t e, e2;
    bw_hack_req_t h = {2, 0, 1, 0xDEADBEEF, 200}, h2;
    static const uint8_t gold_sub[14] = {0x34, 0x12, 0xFB, 0xFF, 0xBC, 0x02, 0x00, 0x40, 30, 100, 90, 7, 9, 1};
    static const uint8_t gold_hack[10] = {2, 0, 1, 0, 0xEF, 0xBE, 0xAD, 0xDE, 0xC8, 0x00};
    CHECK(bw_pack_sub_state(p, &s) == 14 && !memcmp(p, gold_sub, 14));
    CHECK(!bw_unpack_sub_state(p, 14, &s2) && s2.x == -5 && s2.y == 700 && s2.heading == 0x4000);
    CHECK(bw_unpack_sub_state(p, 13, &s2) == -1);
    CHECK(bw_pack_hack_req(p, &h) == 10 && !memcmp(p, gold_hack, 10));
    CHECK(!bw_unpack_hack_req(p, 10, &h2) && h2.seed == 0xDEADBEEF && h2.time_limit_ds == 200);
    memset(&e, 0, sizeof e);
    e.ping_id = 7; e.mode = 1; e.n = 2;
    e.c[0].bearing = 100; e.c[0].range = 300; e.c[0].kind = BW_K_MINE; e.c[0].strength = 9;
    e.c[1].bearing = 65535; e.c[1].range = 1; e.c[1].kind = BW_K_EXIT; e.c[1].strength = 255;
    CHECK(bw_pack_echo(p, &e) == 16);
    CHECK(!bw_unpack_echo(p, 16, &e2) && e2.n == 2 && e2.c[1].bearing == 65535 && e2.c[0].range == 300);
    CHECK(bw_unpack_echo(p, 15, &e2) == -1);
}

static void test_rng_puzzle(void) {
    uint32_t s = 1;
    uint8_t n, t[BW_HACK_MAX], v[BW_HACK_MAX];
    int i;
    /* golden xorshift32 values (mirrored in game/tests/test_proto.py) */
    CHECK(bw_rng_next(&s) == 270369u);
    CHECK(bw_rng_next(&s) == 67634689u);
    bw_hack_generate(0xC0FFEE, 1, &n, t, v);
    CHECK(n == 4);
    for (i = 0; i < n; i++) CHECK(t[i] < 8 && v[i] < 8 && t[i] != v[i]);
    bw_hack_generate(0xC0FFEE, 9, &n, t, v);
    CHECK(n == BW_HACK_MAX);
}

static void feed(bw_console_t *c, uint8_t type, const uint8_t *p, uint32_t n) { bw_console_on_frame(c, type, p, n); }

static void test_flow(void) {
    bw_console_t c;
    uint8_t p[256];
    uint32_t t = 0;
    int i;
    nsent = 0;
    bw_console_init(&c, cap_send, NULL);
    CHECK(c.phase == BW_PH_TITLE);
    bw_console_tick(&c, t, BW_B_START, 0, 0);
    CHECK(last_of(BW_T_READY) != NULL);
    bw_console_tick(&c, t += 16, 0, 0, 0);
    { bw_game_start_t g = {1, 0, 42, 600}; feed(&c, BW_T_GAME_START, p, bw_pack_game_start(p, &g)); }
    CHECK(c.phase == BW_PH_PLAY && c.game.max_range == 600);
    { bw_sub_state_t s = {1, 100, 200, 0, 10, 100, 100, 0, 0, 0}; feed(&c, BW_T_SUB_STATE, p, bw_pack_sub_state(p, &s)); }
    CHECK(c.have_sub && c.sub.x == 100);
    /* active ping */
    bw_console_tick(&c, t += 16, BW_B_CROSS, 0, 0);
    CHECK(last_of(BW_T_PING_CMD) && last_of(BW_T_PING_CMD)->p[1] == BW_PING_ACTIVE);
    /* cooldown: second press too early is ignored */
    bw_console_tick(&c, t += 16, 0, 0, 0);
    i = c.pings_sent;
    bw_console_tick(&c, t += 16, BW_B_CROSS, 0, 0);
    CHECK(c.pings_sent == i);
    /* echo: one mine due north at 100 -> world (100, 100) */
    {
        bw_echo_t e;
        memset(&e, 0, sizeof e);
        e.ping_id = 1; e.mode = 1; e.n = 1;
        e.c[0].bearing = 0; e.c[0].range = 100; e.c[0].kind = BW_K_MINE; e.c[0].strength = 200;
        feed(&c, BW_T_ECHO, p, bw_pack_echo(p, &e));
    }
    CHECK(c.ncontacts == 1 && c.contacts[0].wx > 99.0f && c.contacts[0].wx < 101.0f && c.contacts[0].wy > 99.0f &&
          c.contacts[0].wy < 101.0f);
    /* mark it */
    bw_console_tick(&c, t += 16, 0, 0, 0);
    bw_console_tick(&c, t += 16, BW_B_TRIANGLE, 0, 0);
    CHECK(last_of(BW_T_MARK) && last_of(BW_T_MARK)->p[0] == 1 && last_of(BW_T_MARK)->p[1] == 0);
    /* nub -> PILOT */
    bw_console_tick(&c, t += 100, 0, 100, -100);
    CHECK(last_of(BW_T_PILOT) && (int8_t)last_of(BW_T_PILOT)->p[0] == 100);
    nsent = 0;
    bw_console_tick(&c, t += 100, 0, 0, 0);
    CHECK(last_of(BW_T_PILOT) && last_of(BW_T_PILOT)->p[0] == 0); /* release is sent once */
    /* hack: solve with the bot */
    { bw_hack_req_t h = {1, 0, 1, 1234, 200}; feed(&c, BW_T_HACK_REQ, p, bw_pack_hack_req(p, &h)); }
    CHECK(c.phase == BW_PH_HACK && c.hack_n == 4);
    nsent = 0;
    for (i = 0; i < 400 && c.phase == BW_PH_HACK; i++) {
        t += 16;
        bw_console_tick(&c, t, bw_bot_buttons(&c, (uint32_t)i, t, 2500), 0, 0);
    }
    CHECK(c.phase == BW_PH_PLAY && c.hacks_ok == 1);
    CHECK(last_of(BW_T_HACK_RESULT) && last_of(BW_T_HACK_RESULT)->p[0] == 1 && last_of(BW_T_HACK_RESULT)->p[1] == 1);
    /* hack timeout -> ok = 0 */
    { bw_hack_req_t h = {2, 0, 0, 99, 10}; feed(&c, BW_T_HACK_REQ, p, bw_pack_hack_req(p, &h)); }
    bw_console_tick(&c, t += 500, 0, 0, 0);
    bw_console_tick(&c, t += 600, 0, 0, 0);
    CHECK(c.phase == BW_PH_PLAY && c.hacks_failed == 1 && last_of(BW_T_HACK_RESULT)->p[1] == 0);
    /* wrong submit costs time */
    { bw_hack_req_t h = {3, 0, 0, 7, 100}; feed(&c, BW_T_HACK_REQ, p, bw_pack_hack_req(p, &h)); }
    {
        uint32_t before = c.hack_deadline_ms;
        bw_console_tick(&c, t += 16, BW_B_CROSS, 0, 0);
        CHECK(c.phase == BW_PH_HACK && c.hack_deadline_ms == before - BW_HACK_PENALTY_MS);
    }
    bw_console_tick(&c, t += 16, BW_B_CIRCLE, 0, 0);
    CHECK(c.phase == BW_PH_PLAY && c.hacks_failed == 2);
    /* win */
    { bw_event_t ev = {BW_EV_WIN, 0}; feed(&c, BW_T_EVENT, p, bw_pack_event(p, &ev)); }
    CHECK(c.phase == BW_PH_OVER && c.outcome == 1);
}

static void test_demo_app(void) {
    static bw_app_t a;
    static uint32_t fb[BW_STRIDE * BW_SCREEN_H];
    bw_gfx_t g = {fb};
    uint32_t f;
    bw_app_init_demo(&a);
    for (f = 0; f < 60 * 60 && a.con.phase != BW_PH_OVER; f++) {
        uint32_t now = f * 1000u / 60u;
        bw_app_step(&a, now, bw_bot_buttons(&a.con, f, now, 2500), 0, 0);
        if (f % 97 == 0) bw_view_draw(&g, &a.con, a.io_name);
    }
    CHECK(a.con.link_up);
    CHECK(a.con.echoes_rx > 3);
    CHECK(a.con.hacks_ok == 1);
    CHECK(a.con.phase == BW_PH_OVER && a.con.outcome == 1);
    CHECK(a.link.parser.crc_errors == 0 && a.demo_mac.link.parser.crc_errors == 0);
}

int main(void) {
    test_golden();
    test_rng_puzzle();
    test_flow();
    test_demo_app();
    if (fails) { fprintf(stderr, "%d check(s) failed\n", fails); return 1; }
    printf("game/psp host tests: all passed\n");
    return 0;
}
