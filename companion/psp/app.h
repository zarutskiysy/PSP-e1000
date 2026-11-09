/* app.h — the companion's UI state machine. Plain C with no PSP calls, so it is unit-tested on the Mac.
 * It owns everything the Mac tells us and every decision the buttons make; rendering only reads it. */
#ifndef PC_APP_H
#define PC_APP_H
#include <stdint.h>

#include "../proto_companion.h"

enum { AP_NONE = 0, AP_SHOWING = 1, AP_WANT_SEND = 2, AP_SENT = 3 };
enum { TOAST_INFO = 0, TOAST_OK = 1, TOAST_ERR = 2 };

#define APP_ARM_MS 450u        /* X/O ignored this long after an approval appears */
#define APP_ACK_WAIT_MS 6000u  /* no APPROVAL_CLOSE after this: tell the user we do not know */
#define APP_CHIP_MS 4000u      /* selected action chip stays visible (and X armed) this long */
#define APP_CONFIRM_MS 3000u   /* window for the second X on Interrupt */
#define APP_LINK_TIMEOUT_MS 3500u

typedef int (*app_emit_fn)(void *ctx, uint8_t type, const void *payload, uint32_t len);

typedef struct {
    uint8_t enabled;
    char reason[PC_REASON_MAX + 1];
} app_action_t;

typedef struct {
    int phase;
    uint32_t id;
    uint8_t kind, flags, pending, decision, armed;
    uint16_t timeout_s;
    uint32_t shown_ms, sent_ms;
    char title[PC_TITLE_MAX + 1];
    char detail[PC_DETAIL_MAX + 1];
} app_approval_t;

typedef struct {
    app_emit_fn emit;
    void *emit_ctx;

    int link_up;
    uint32_t peer_boot_id;
    uint8_t conn, mode, caps, sess_index, sess_count;
    char label[PC_LABEL_MAX + 1];

    uint8_t agent;
    char activity[PC_ACTIVITY_MAX + 1];
    char note[80]; /* local status while unlinked (USB waiting, load errors) */

    app_action_t actions[PC_ACT_COUNT];
    int selected, menu_open;
    uint32_t chip_until;
    uint32_t confirm_until;
    uint16_t next_req;

    app_approval_t ap;

    char toast[PC_TEXT_MAX + 1];
    uint32_t toast_until;
    int toast_kind;

    int diag;
    uint8_t pending_anim;
    uint32_t prev_buttons;

    /* counters for diagnostics and tests */
    uint32_t rx_msgs, rx_bad, tx_drop;
    uint32_t last_err_ms;
} app_t;

void app_init(app_t *a, app_emit_fn emit, void *ctx);
void app_set_note(app_t *a, const char *note);
void app_on_link(app_t *a, int up, uint32_t now_ms);
/* One decoded link frame. Returns 1 if accepted, 0 if it was malformed/unknown (and ignored). */
int app_on_frame(app_t *a, uint8_t type, const uint8_t *p, uint32_t len, uint32_t now_ms);
void app_on_buttons(app_t *a, uint32_t held, uint32_t now_ms);
void app_tick(app_t *a, uint32_t now_ms);

/* Effective pet state: the Mac's, or a local one when there is no link. */
uint8_t app_pet_state(const app_t *a);
const char *app_status_text(const app_t *a);
const char *app_action_label(int id);
int app_chip_visible(const app_t *a, uint32_t now_ms);
int app_toast_visible(const app_t *a, uint32_t now_ms);
#endif
