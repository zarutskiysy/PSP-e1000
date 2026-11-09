#include "app.h"

#include <stdio.h>
#include <string.h>

/* Wrap-safe "now has reached t" for free-running u32 millisecond clocks. */
static int reached(uint32_t now, uint32_t t) { return (int32_t)(now - t) >= 0; }

static const char *const k_labels[PC_ACT_COUNT] = {
    "Continue task", "Summarize progress", "Run project tests", "Inspect recent errors", "Interrupt task"};

const char *app_action_label(int id) { return (id >= 0 && id < PC_ACT_COUNT) ? k_labels[id] : "?"; }

static void toast(app_t *a, int kind, const char *text, uint32_t now, uint32_t ms) {
    snprintf(a->toast, sizeof a->toast, "%s", text);
    a->toast_kind = kind;
    a->toast_until = (now + ms) | 1u;
}

static void reset_session_view(app_t *a) {
    int i;
    a->conn = PC_CONN_NONE;
    a->mode = PC_MODE_NONE;
    a->caps = 0;
    a->sess_index = a->sess_count = 0;
    a->label[0] = 0;
    a->agent = PC_AG_SLEEPING;
    a->activity[0] = 0;
    for (i = 0; i < PC_ACT_COUNT; i++) {
        a->actions[i].enabled = 0;
        snprintf(a->actions[i].reason, sizeof a->actions[i].reason, "Not connected");
    }
    a->menu_open = 0;
    a->chip_until = 0;
    a->confirm_until = 0;
}

void app_init(app_t *a, app_emit_fn emit, void *ctx) {
    memset(a, 0, sizeof *a);
    a->emit = emit;
    a->emit_ctx = ctx;
    reset_session_view(a);
    snprintf(a->note, sizeof a->note, "Waiting for Mac...");
}

void app_set_note(app_t *a, const char *note) { snprintf(a->note, sizeof a->note, "%s", note); }

static void close_approval(app_t *a) { memset(&a->ap, 0, sizeof a->ap); }

void app_on_link(app_t *a, int up, uint32_t now) {
    if (up == a->link_up) return;
    a->link_up = up;
    if (!up) {
        /* Fail closed: an overlay must not outlive the link it was answered over. */
        if (a->ap.phase != AP_NONE) toast(a, TOAST_ERR, "Link lost: approval not sent", now, 4000);
        close_approval(a);
        reset_session_view(a);
    }
}

static int send_approval(app_t *a) {
    uint8_t b[6];
    b[0] = PC_VERSION;
    psp_link_put_u32(b + 1, a->ap.id);
    b[5] = a->ap.decision;
    return a->emit(a->emit_ctx, PC_T_APPROVAL_RESP, b, sizeof b);
}

static void on_approval_req(app_t *a, pc_rd_t *r, uint32_t now) {
    app_approval_t n;
    memset(&n, 0, sizeof n);
    n.id = pc_rd_u32(r);
    n.kind = pc_rd_u8(r);
    n.flags = pc_rd_u8(r);
    n.timeout_s = pc_rd_u16(r);
    n.pending = pc_rd_u8(r);
    pc_rd_str(r, n.title, sizeof n.title);
    pc_rd_str(r, n.detail, sizeof n.detail);
    if (r->bad || n.id == 0) {
        r->bad = 1;
        return;
    }
    if (a->ap.phase != AP_NONE && a->ap.id == n.id) { /* re-send of the same request: keep its state */
        a->ap.pending = n.pending;
        return;
    }
    n.phase = AP_SHOWING;
    n.shown_ms = now;
    a->ap = n;
    a->menu_open = 0;
    a->chip_until = 0;
    a->pending_anim = PC_ANIM_BOUNCE;
}

static void on_approval_close(app_t *a, pc_rd_t *r, uint32_t now) {
    char text[PC_TEXT_MAX + 1];
    uint32_t id = pc_rd_u32(r);
    uint8_t reason = pc_rd_u8(r);
    int was_ours;
    pc_rd_str(r, text, sizeof text);
    if (r->bad) return;
    was_ours = a->ap.phase != AP_NONE && a->ap.id == id;
    if (!was_ours) return;
    close_approval(a);
    switch (reason) {
    case PC_CLOSE_ALLOWED:
        toast(a, TOAST_OK, text[0] ? text : "Allowed", now, 2500);
        a->pending_anim = PC_ANIM_ALLOWED;
        break;
    case PC_CLOSE_DENIED:
        toast(a, TOAST_INFO, text[0] ? text : "Denied", now, 2500);
        a->pending_anim = PC_ANIM_DENIED;
        break;
    case PC_CLOSE_HIDDEN:
        break;
    default:
        toast(a, TOAST_ERR, text[0] ? text : "Approval closed", now, 3500);
        break;
    }
}

static void on_actions(app_t *a, pc_rd_t *r) {
    uint32_t n = pc_rd_u8(r), i;
    for (i = 0; i < n && !r->bad; i++) {
        uint8_t id = pc_rd_u8(r), en = pc_rd_u8(r);
        char reason[PC_REASON_MAX + 1];
        pc_rd_str(r, reason, sizeof reason);
        if (!r->bad && id < PC_ACT_COUNT) {
            a->actions[id].enabled = en ? 1 : 0;
            memcpy(a->actions[id].reason, reason, sizeof reason);
        }
    }
}

/* Tells the Mac a message was dropped, at most once a second. */
static void report_bad(app_t *a, uint8_t type, uint32_t now) {
    uint8_t b[10];
    a->rx_bad++;
    if (a->last_err_ms && !reached(now, a->last_err_ms + 1000u)) return;
    a->last_err_ms = now | 1u;
    psp_link_put_u16(b, 1);
    memcpy(b + 2, "bad msg", 7);
    b[9] = type;
    (void)a->emit(a->emit_ctx, PSP_LINK_T_ERROR, b, sizeof b);
}

int app_on_frame(app_t *a, uint8_t type, const uint8_t *p, uint32_t len, uint32_t now) {
    pc_rd_t r;
    if (type == PSP_LINK_T_HELLO || type == PSP_LINK_T_HELLO_ACK) {
        app_on_link(a, 1, now);
        return 1;
    }
    if (type == PSP_LINK_T_BYE) {
        app_on_link(a, 0, now);
        return 1;
    }
    if (type < PC_T_CONN || type > PC_T_HEARTBEAT) return 0;
    pc_rd_init(&r, p, len);
    if (pc_rd_u8(&r) != PC_VERSION || r.bad) {
        report_bad(a, type, now);
        return 0;
    }
    switch (type) {
    case PC_T_CONN: {
        char label[PC_LABEL_MAX + 1];
        uint8_t conn = pc_rd_u8(&r), mode = pc_rd_u8(&r), caps = pc_rd_u8(&r), idx = pc_rd_u8(&r), cnt = pc_rd_u8(&r);
        pc_rd_str(&r, label, sizeof label);
        if (!r.bad) {
            a->conn = conn;
            a->mode = mode;
            a->caps = caps;
            a->sess_index = idx;
            a->sess_count = cnt;
            memcpy(a->label, label, sizeof label);
        }
        break;
    }
    case PC_T_AGENT: {
        uint8_t s = pc_rd_u8(&r);
        if (!r.bad && s < PC_AG_COUNT) a->agent = s;
        else r.bad = 1;
        break;
    }
    case PC_T_ACTIVITY: {
        char t[PC_ACTIVITY_MAX + 1];
        pc_rd_str(&r, t, sizeof t);
        if (!r.bad) memcpy(a->activity, t, sizeof t);
        break;
    }
    case PC_T_ACTIONS:
        on_actions(a, &r);
        break;
    case PC_T_APPROVAL_REQ:
        on_approval_req(a, &r, now);
        break;
    case PC_T_APPROVAL_CLOSE:
        on_approval_close(a, &r, now);
        break;
    case PC_T_ACTION_ACK: {
        char t[PC_TEXT_MAX + 1];
        uint16_t req = pc_rd_u16(&r);
        uint8_t status = pc_rd_u8(&r);
        pc_rd_str(&r, t, sizeof t);
        (void)req;
        if (!r.bad) toast(a, status == PC_ACK_DONE ? TOAST_OK : status == PC_ACK_ACCEPTED ? TOAST_INFO : TOAST_ERR,
                          t[0] ? t : "Action finished", now, 3000);
        break;
    }
    case PC_T_ANIM: {
        uint8_t an = pc_rd_u8(&r);
        if (!r.bad) a->pending_anim = an;
        break;
    }
    case PC_T_HEARTBEAT: {
        uint32_t boot = pc_rd_u32(&r);
        if (!r.bad) a->peer_boot_id = boot;
        break;
    }
    default:
        return 0;
    }
    if (r.bad) {
        report_bad(a, type, now);
        return 0;
    }
    a->rx_msgs++;
    return 1;
}

static void send_action(app_t *a, uint8_t action, uint32_t now) {
    uint8_t b[4];
    b[0] = PC_VERSION;
    psp_link_put_u16(b + 1, ++a->next_req);
    b[3] = action;
    if (a->emit(a->emit_ctx, PC_T_ACTION, b, sizeof b) != 0) {
        a->tx_drop++;
        toast(a, TOAST_ERR, "Could not send: link busy", now, 2500);
    }
}

static void execute_selected(app_t *a, uint32_t now) {
    int id = a->selected;
    if (!a->link_up) {
        toast(a, TOAST_ERR, "No link to the Mac", now, 2500);
        return;
    }
    if (!a->actions[id].enabled) {
        toast(a, TOAST_ERR, a->actions[id].reason[0] ? a->actions[id].reason : "Unavailable", now, 3000);
        return;
    }
    if (id == PC_ACT_INTERRUPT && !(a->confirm_until && !reached(now, a->confirm_until))) {
        a->confirm_until = (now + APP_CONFIRM_MS) | 1u;
        a->chip_until = now + APP_CONFIRM_MS;
        toast(a, TOAST_INFO, "Press X again to interrupt", now, APP_CONFIRM_MS);
        return;
    }
    a->confirm_until = 0;
    a->menu_open = 0;
    a->chip_until = 0;
    send_action(a, (uint8_t)id, now);
}

static void report_buttons(app_t *a, uint32_t changed, uint32_t held) {
    int bit;
    for (bit = 0; bit < 12; bit++) {
        uint32_t m = 1u << bit;
        if (changed & m) {
            uint8_t b[3];
            b[0] = PC_VERSION;
            b[1] = (uint8_t)bit;
            b[2] = (held & m) ? 1 : 0;
            if (a->link_up && a->emit(a->emit_ctx, PC_T_BUTTON, b, sizeof b) != 0) a->tx_drop++;
        }
    }
}

static void move_selection(app_t *a, int d, uint32_t now) {
    a->selected = (a->selected + d + PC_ACT_COUNT) % PC_ACT_COUNT;
    a->confirm_until = 0;
    a->chip_until = now + APP_CHIP_MS;
}

void app_on_buttons(app_t *a, uint32_t held, uint32_t now) {
    uint32_t pressed = held & ~a->prev_buttons;
    uint32_t changed = held ^ a->prev_buttons;
    app_approval_t *ap = &a->ap;
    a->prev_buttons = held;
    if (changed) report_buttons(a, changed, held);

    if (pressed & PC_BTN_SELECT) a->diag = !a->diag;

    if (ap->phase != AP_NONE) {
        if (ap->phase == AP_SHOWING) {
            /* Arming: a press that began before the overlay appeared must not answer it. */
            if (!ap->armed) {
                if (!(held & (PC_BTN_CROSS | PC_BTN_CIRCLE)) && reached(now, ap->shown_ms + APP_ARM_MS)) ap->armed = 1;
            } else if (ap->flags & PC_AF_ACTIONABLE) {
                if (pressed & PC_BTN_CROSS) ap->decision = PC_DECISION_ALLOW;
                else if (pressed & PC_BTN_CIRCLE) ap->decision = PC_DECISION_DENY;
                if (ap->decision) {
                    ap->phase = AP_WANT_SEND;
                    ap->sent_ms = now;
                }
            } else if (pressed & PC_BTN_CIRCLE) {
                close_approval(a); /* notification only: dismiss locally, Codex is still waiting */
            }
        }
        return;
    }

    if (pressed & PC_BTN_START) {
        a->menu_open = !a->menu_open;
        a->confirm_until = 0;
        a->chip_until = 0;
    }
    if (pressed & PC_BTN_UP) move_selection(a, -1, now);
    if (pressed & PC_BTN_DOWN) move_selection(a, 1, now);
    if (pressed & PC_BTN_CROSS) {
        if (a->menu_open || app_chip_visible(a, now)) execute_selected(a, now);
    }
    if (pressed & PC_BTN_CIRCLE) {
        a->menu_open = 0;
        a->chip_until = 0;
        a->confirm_until = 0;
        a->toast_until = 0;
    }
    if ((pressed & (PC_BTN_L | PC_BTN_R)) && a->link_up && a->sess_count > 1)
        send_action(a, (pressed & PC_BTN_L) ? PC_ACT_SESSION_PREV : PC_ACT_SESSION_NEXT, now);
}

void app_tick(app_t *a, uint32_t now) {
    if (a->ap.phase == AP_WANT_SEND) {
        if (send_approval(a) == 0) {
            a->ap.phase = AP_SENT;
            a->ap.sent_ms = now;
        } else if (reached(now, a->ap.sent_ms + APP_ACK_WAIT_MS)) {
            toast(a, TOAST_ERR, "Could not send decision", now, 3500);
            close_approval(a);
        }
    } else if (a->ap.phase == AP_SENT && reached(now, a->ap.sent_ms + APP_ACK_WAIT_MS)) {
        toast(a, TOAST_ERR, "No confirmation from Mac", now, 3500);
        close_approval(a);
    }
    if (a->confirm_until && reached(now, a->confirm_until)) a->confirm_until = 0;
    if (a->toast_until && reached(now, a->toast_until)) a->toast_until = 0;
}

uint8_t app_pet_state(const app_t *a) {
    if (!a->link_up) return PC_AG_OFFLINE;
    return a->agent;
}

const char *app_status_text(const app_t *a) {
    if (!a->link_up) return a->note;
    if (a->activity[0]) return a->activity;
    return a->conn == PC_CONN_ATTACHED ? "Idle" : "Type $psp-connect in Codex";
}

int app_chip_visible(const app_t *a, uint32_t now) { return a->chip_until && !reached(now, a->chip_until); }

int app_toast_visible(const app_t *a, uint32_t now) { return a->toast_until && !reached(now, a->toast_until); }
