/* test_app.c — logic tests for the PSP state machine, under ASan/UBSan. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../app.h"

static struct { uint8_t type; uint8_t data[32]; uint32_t len; } sent[64];
static int nsent, fail_emit;

static int emit(void *c, uint8_t t, const void *p, uint32_t n) {
    (void)c;
    if (fail_emit) return -1;
    if (t == PC_T_BUTTON) return 0; /* counted separately in test_buttons_reported */
    assert(nsent < 64 && n <= 32);
    sent[nsent].type = t;
    sent[nsent].len = n;
    memcpy(sent[nsent].data, p, n);
    nsent++;
    return 0;
}

static app_t a;

static uint32_t put_str(uint8_t *b, uint32_t o, const char *s) {
    uint32_t n = (uint32_t)strlen(s);
    b[o++] = (uint8_t)n;
    memcpy(b + o, s, n);
    return o + n;
}

static uint32_t mk_req(uint8_t *b, uint32_t id, uint8_t flags) {
    uint32_t o = 0;
    b[o++] = PC_VERSION;
    psp_link_put_u32(b + o, id); o += 4;
    b[o++] = PC_KIND_COMMAND;
    b[o++] = flags;
    psp_link_put_u16(b + o, 120); o += 2;
    b[o++] = 1;
    o = put_str(b, o, "Run command?");
    return put_str(b, o, "npm test");
}

static uint32_t mk_close(uint8_t *b, uint32_t id, uint8_t reason) {
    uint32_t o = 0;
    b[o++] = PC_VERSION;
    psp_link_put_u32(b + o, id); o += 4;
    b[o++] = reason;
    return put_str(b, o, "");
}

static void fresh(void) {
    app_init(&a, emit, NULL);
    nsent = 0;
    fail_emit = 0;
    app_on_link(&a, 1, 1000);
}

static void show(uint32_t id, uint8_t flags, uint32_t now) {
    uint8_t b[256];
    uint32_t n = mk_req(b, id, flags);
    assert(app_on_frame(&a, PC_T_APPROVAL_REQ, b, n, now) == 1);
    assert(a.ap.phase == AP_SHOWING && a.ap.id == id);
}

static void press(uint32_t btn, uint32_t now) {
    app_on_buttons(&a, btn, now);
    app_on_buttons(&a, 0, now + 16);
}

static void test_state_messages(void) {
    uint8_t b[128];
    uint32_t o;
    fresh();
    b[0] = PC_VERSION; b[1] = PC_CONN_ATTACHED; b[2] = PC_MODE_MANAGED; b[3] = PC_CAP_ACTIONS; b[4] = 0; b[5] = 2;
    o = put_str(b, 6, "repo");
    assert(app_on_frame(&a, PC_T_CONN, b, o, 1) == 1);
    assert(a.conn == PC_CONN_ATTACHED && a.mode == PC_MODE_MANAGED && a.sess_count == 2 && !strcmp(a.label, "repo"));
    b[1] = PC_AG_EDITING;
    assert(app_on_frame(&a, PC_T_AGENT, b, 2, 1) == 1 && app_pet_state(&a) == PC_AG_EDITING);
    b[1] = PC_AG_COUNT; /* out of range: ignored */
    assert(app_on_frame(&a, PC_T_AGENT, b, 2, 1) == 0 && app_pet_state(&a) == PC_AG_EDITING);
    o = put_str(b, 1, "Editing main.py");
    assert(app_on_frame(&a, PC_T_ACTIVITY, b, o, 1) == 1 && !strcmp(app_status_text(&a), "Editing main.py"));
    /* non-ASCII is neutralised */
    b[1] = 3; b[2] = 'a'; b[3] = 0xFF; b[4] = 0x07;
    assert(app_on_frame(&a, PC_T_ACTIVITY, b, 5, 1) == 1 && !strcmp(a.activity, "a??"));
}

static void test_bad_input(void) {
    uint8_t b[16] = {PC_VERSION, 200};
    fresh();
    strcpy(a.activity, "keep");
    assert(app_on_frame(&a, PC_T_ACTIVITY, b, 2, 1) == 0); /* length 200, nothing behind it */
    assert(!strcmp(a.activity, "keep") && a.rx_bad == 1);
    b[0] = PC_VERSION + 1;
    assert(app_on_frame(&a, PC_T_ACTIVITY, b, 2, 1) == 0 && a.rx_bad == 2);
    assert(app_on_frame(&a, PC_T_ACTIVITY, b, 0, 1) == 0);
    assert(app_on_frame(&a, 0x55, b, 2, 1) == 0); /* foreign type */
}

static void test_approval_arming(void) {
    fresh();
    /* X already held when the overlay appears must not answer it, even after the arm delay */
    app_on_buttons(&a, PC_BTN_CROSS, 2000);
    show(7, PC_AF_ACTIONABLE, 2000);
    app_on_buttons(&a, PC_BTN_CROSS, 3000);
    app_tick(&a, 3000);
    assert(a.ap.phase == AP_SHOWING && !a.ap.armed && nsent == 0);
    app_on_buttons(&a, 0, 3016);
    assert(a.ap.armed == 1);
    /* a fresh press within the arm window of a new overlay does nothing */
    fresh();
    show(8, PC_AF_ACTIONABLE, 2000);
    press(PC_BTN_CROSS, 2100);
    app_tick(&a, 2120);
    assert(a.ap.phase == AP_SHOWING && nsent == 0);
}

static void arm(uint32_t now) {
    app_on_buttons(&a, 0, now);
    assert(a.ap.armed == 1);
}

static void test_approval_flow(void) {
    uint8_t b[64];
    uint32_t n;
    fresh();
    show(0xAABBCCDD, PC_AF_ACTIONABLE, 2000);
    arm(3000);
    press(PC_BTN_CROSS, 3100);
    app_tick(&a, 3120);
    assert(nsent == 1 && sent[0].type == PC_T_APPROVAL_RESP && sent[0].len == 6);
    assert(psp_link_get_u32(sent[0].data + 1) == 0xAABBCCDDu && sent[0].data[5] == PC_DECISION_ALLOW);
    assert(a.ap.phase == AP_SENT);
    /* mashing after the decision never sends a second one */
    press(PC_BTN_CROSS, 3200); press(PC_BTN_CIRCLE, 3300);
    app_tick(&a, 3400);
    assert(nsent == 1);
    /* a close for another id leaves this one alone */
    n = mk_close(b, 1234, PC_CLOSE_ALLOWED);
    assert(app_on_frame(&a, PC_T_APPROVAL_CLOSE, b, n, 3500) == 1 && a.ap.phase == AP_SENT);
    /* the overlay only ends when the Mac says what happened */
    n = mk_close(b, 0xAABBCCDD, PC_CLOSE_ALLOWED);
    assert(app_on_frame(&a, PC_T_APPROVAL_CLOSE, b, n, 3600) == 1 && a.ap.phase == AP_NONE);
    assert(a.pending_anim == PC_ANIM_ALLOWED && app_toast_visible(&a, 3700));
    /* deny path */
    fresh();
    show(9, PC_AF_ACTIONABLE, 2000);
    arm(3000);
    press(PC_BTN_CIRCLE, 3100);
    app_tick(&a, 3120);
    assert(nsent == 1 && sent[0].data[5] == PC_DECISION_DENY);
    /* no confirmation: the UI says so instead of assuming success */
    app_tick(&a, 3120 + APP_ACK_WAIT_MS + 10);
    assert(a.ap.phase == AP_NONE && a.toast_kind == TOAST_ERR);
}

static void test_approval_notification_only(void) {
    fresh();
    show(10, 0, 2000);
    arm(3000);
    press(PC_BTN_CROSS, 3100);
    app_tick(&a, 3120);
    assert(a.ap.phase == AP_SHOWING && nsent == 0);
    press(PC_BTN_CIRCLE, 3200);
    app_tick(&a, 3220);
    assert(a.ap.phase == AP_NONE && nsent == 0); /* dismissed locally; nothing decided */
}

static void test_approval_replaced_and_resend(void) {
    fresh();
    show(11, PC_AF_ACTIONABLE, 2000);
    arm(3000);
    /* the same request re-sent keeps arming and timing */
    show(11, PC_AF_ACTIONABLE, 3100);
    assert(a.ap.armed == 1 && a.ap.shown_ms == 2000);
    /* a different id starts over: the old answer cannot apply to it */
    show(12, PC_AF_ACTIONABLE, 3200);
    assert(a.ap.armed == 0 && a.ap.id == 12);
    press(PC_BTN_CROSS, 3300);
    app_tick(&a, 3320);
    assert(nsent == 0);
}

static void test_link_loss_fails_closed(void) {
    fresh();
    show(13, PC_AF_ACTIONABLE, 2000);
    arm(3000);
    app_on_link(&a, 0, 3050);
    assert(a.ap.phase == AP_NONE && app_pet_state(&a) == PC_AG_OFFLINE);
    press(PC_BTN_CROSS, 3100);
    app_tick(&a, 3120);
    assert(nsent == 0);
    /* a decision that cannot be queued is retried, then given up on */
    fresh();
    show(14, PC_AF_ACTIONABLE, 2000);
    arm(3000);
    press(PC_BTN_CROSS, 3100);
    fail_emit = 1;
    app_tick(&a, 3120);
    assert(a.ap.phase == AP_WANT_SEND);
    fail_emit = 0;
    app_tick(&a, 3140);
    assert(a.ap.phase == AP_SENT && nsent == 1);
}

static void enable_all(void) {
    int i;
    for (i = 0; i < PC_ACT_COUNT; i++) a.actions[i].enabled = 1;
}

static void test_actions(void) {
    fresh();
    enable_all();
    /* X with nothing selected on screen does nothing */
    press(PC_BTN_CROSS, 2000);
    assert(nsent == 0);
    /* DOWN shows the chip and arms X */
    press(PC_BTN_DOWN, 2100);
    assert(a.selected == 1 && app_chip_visible(&a, 2200));
    press(PC_BTN_CROSS, 2300);
    assert(nsent == 1 && sent[0].type == PC_T_ACTION && sent[0].data[3] == PC_ACT_SUMMARIZE);
    /* chip expires */
    press(PC_BTN_DOWN, 3000);
    nsent = 0;
    press(PC_BTN_CROSS, 3000 + APP_CHIP_MS + 100);
    assert(nsent == 0);
    /* disabled: explains, sends nothing */
    fresh();
    strcpy(a.actions[0].reason, "Observe only");
    a.menu_open = 1;
    press(PC_BTN_CROSS, 2000);
    assert(nsent == 0 && app_toast_visible(&a, 2100) && !strcmp(a.toast, "Observe only"));
    /* interrupt needs a second X */
    fresh();
    enable_all();
    a.selected = PC_ACT_INTERRUPT;
    a.menu_open = 1;
    press(PC_BTN_CROSS, 2000);
    assert(nsent == 0 && a.confirm_until);
    press(PC_BTN_CROSS, 2500);
    assert(nsent == 1 && sent[0].data[3] == PC_ACT_INTERRUPT);
    /* ...and the confirmation window expires */
    fresh();
    enable_all();
    a.selected = PC_ACT_INTERRUPT;
    a.menu_open = 1;
    press(PC_BTN_CROSS, 2000);
    app_tick(&a, 2000 + APP_CONFIRM_MS + 50);
    assert(a.confirm_until == 0);
    press(PC_BTN_CROSS, 2000 + APP_CONFIRM_MS + 100);
    assert(nsent == 0);
    /* START toggles, O closes */
    fresh();
    press(PC_BTN_START, 2000);
    assert(a.menu_open == 1);
    press(PC_BTN_CIRCLE, 2100);
    assert(a.menu_open == 0);
}

static void test_session_buttons(void) {
    fresh();
    press(PC_BTN_R, 2000);
    assert(nsent == 0); /* one session: nothing to switch to */
    a.sess_count = 2;
    press(PC_BTN_R, 2100);
    assert(nsent == 1 && sent[0].data[3] == PC_ACT_SESSION_NEXT);
    press(PC_BTN_L, 2200);
    assert(nsent == 2 && sent[1].data[3] == PC_ACT_SESSION_PREV);
}

static void test_clock_wrap(void) {
    uint32_t t = 0xFFFFFF00u;
    fresh();
    show(15, PC_AF_ACTIONABLE, t);
    app_on_buttons(&a, 0, t + 200);
    assert(!a.ap.armed);
    app_on_buttons(&a, 0, t + 1000); /* past the wrap */
    assert(a.ap.armed);
}

static void test_fuzz(void) {
    uint8_t b[PC_MAX_PAYLOAD];
    int i;
    srand(1234);
    fresh();
    for (i = 0; i < 400000; i++) {
        uint32_t n = (uint32_t)rand() % sizeof b, j;
        uint8_t t = (uint8_t)(0xA0 + rand() % 0x14);
        for (j = 0; j < n; j++) b[j] = (uint8_t)rand();
        if (n) b[0] = PC_VERSION;
        app_on_frame(&a, t, b, n, (uint32_t)i);
        if ((i & 63) == 0) { app_on_buttons(&a, (uint32_t)rand() & 0xFFF, (uint32_t)i); nsent = 0; }
        if ((i & 255) == 0) app_on_link(&a, rand() & 1, (uint32_t)i);
        app_tick(&a, (uint32_t)i);
        nsent = 0;
        assert(a.selected >= 0 && a.selected < PC_ACT_COUNT);
        assert(strlen(a.activity) <= PC_ACTIVITY_MAX && strlen(a.label) <= PC_LABEL_MAX);
        assert(strlen(a.ap.detail) <= PC_DETAIL_MAX && strlen(a.toast) <= PC_TEXT_MAX);
    }
}

int main(void) {
    test_state_messages();
    test_bad_input();
    test_approval_arming();
    test_approval_flow();
    test_approval_notification_only();
    test_approval_replaced_and_resend();
    test_link_loss_fails_closed();
    test_actions();
    test_session_buttons();
    test_clock_wrap();
    test_fuzz();
    puts("test_app: all passed");
    return 0;
}
