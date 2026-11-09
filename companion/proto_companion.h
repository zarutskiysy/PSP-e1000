/*
 * proto_companion.h — PSP AI Companion messages, carried inside psp_link.h frames.
 * Freestanding C99 (compiles with psp-gcc and clang). Python mirror: companion/mac/psp_companion/protocol.py
 * (test_golden.py cross-checks both directions against the C code).
 *
 * Type range 0xA0-0xBF (taken from "future tracks" in psp_link.h). HELLO.app == PC_APP_ID.
 * Every payload starts with u8 version == PC_VERSION; a receiver drops other versions.
 * Integers are little-endian; a "str" is u8 length + that many bytes of printable ASCII.
 * Readers are bounds-checked: a truncated payload sets rd.bad and the message is discarded.
 * Trailing bytes are ignored, so a later minor revision can append fields.
 *
 * Mac -> PSP
 *   CONN            ver, conn u8, mode u8, caps u8, index u8, count u8, label str
 *   AGENT           ver, state u8
 *   ACTIVITY        ver, text str
 *   ACTIONS         ver, n u8, n * { id u8, enabled u8, reason str }
 *   APPROVAL_REQ    ver, id u32, kind u8, flags u8, timeout_s u16, pending u8, title str, detail str
 *   APPROVAL_CLOSE  ver, id u32, reason u8, text str
 *   ACTION_ACK      ver, req u16, status u8, text str
 *   ANIM            ver, anim u8
 * PSP -> Mac
 *   BUTTON          ver, button u8, down u8
 *   ACTION          ver, req u16, action u8
 *   APPROVAL_RESP   ver, id u32, decision u8
 * Both ways
 *   HEARTBEAT       ver, boot_id u32, uptime_ms u32
 * Errors use the common PSP_LINK_T_ERROR frame (u16 code + UTF-8 text).
 */
#ifndef PROTO_COMPANION_H
#define PROTO_COMPANION_H

#include "../common/protocol/psp_link.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PC_APP_ID 4u
#define PC_VERSION 1u
#define PC_MAX_PAYLOAD 384u /* every companion payload fits; far below the HOSTFS 4 KiB limit too */

enum {
    PC_T_CONN = 0xA0,
    PC_T_AGENT = 0xA1,
    PC_T_ACTIVITY = 0xA2,
    PC_T_ACTIONS = 0xA3,
    PC_T_APPROVAL_REQ = 0xA4,
    PC_T_APPROVAL_CLOSE = 0xA5,
    PC_T_ACTION_ACK = 0xA6,
    PC_T_ANIM = 0xA7,
    PC_T_HEARTBEAT = 0xA8,
    PC_T_BUTTON = 0xB0,
    PC_T_ACTION = 0xB1,
    PC_T_APPROVAL_RESP = 0xB2
};

/* string capacities (bytes, without terminator) */
#define PC_LABEL_MAX 24u
#define PC_ACTIVITY_MAX 72u
#define PC_REASON_MAX 40u
#define PC_TITLE_MAX 28u
#define PC_DETAIL_MAX 120u
#define PC_TEXT_MAX 48u

enum { PC_CONN_NONE = 0, PC_CONN_ATTACHED = 1, PC_CONN_RECONNECTING = 2, PC_CONN_ENDED = 3 };
enum { PC_MODE_NONE = 0, PC_MODE_OBSERVE = 1, PC_MODE_HOOKS = 2, PC_MODE_MANAGED = 3, PC_MODE_DEMO = 4 };
enum { PC_CAP_APPROVALS = 1, PC_CAP_ACTIONS = 2, PC_CAP_LIVE_TOOLS = 4 };

enum {
    PC_AG_OFFLINE = 0,
    PC_AG_SLEEPING = 1,
    PC_AG_IDLE = 2,
    PC_AG_THINKING = 3,
    PC_AG_EDITING = 4,
    PC_AG_RUNNING = 5,
    PC_AG_TESTING = 6,
    PC_AG_APPROVAL = 7,
    PC_AG_SUCCESS = 8,
    PC_AG_FAILED = 9,
    PC_AG_TALKING = 10,
    PC_AG_WORKING = 11,
    PC_AG_COUNT = 12
};

enum { PC_ANIM_NONE = 0, PC_ANIM_WAKE = 1, PC_ANIM_CELEBRATE = 2, PC_ANIM_FAIL = 3, PC_ANIM_ALLOWED = 4, PC_ANIM_DENIED = 5, PC_ANIM_BOUNCE = 6 };

enum { PC_KIND_COMMAND = 0, PC_KIND_FILE = 1, PC_KIND_PERMISSION = 2, PC_KIND_OTHER = 3 };
enum { PC_AF_ACTIONABLE = 1, PC_AF_DEMO = 2 };
enum { PC_DECISION_ALLOW = 1, PC_DECISION_DENY = 2 };
enum {
    PC_CLOSE_ALLOWED = 1,
    PC_CLOSE_DENIED = 2,
    PC_CLOSE_TIMEOUT = 3,
    PC_CLOSE_ELSEWHERE = 4, /* answered or cleared by Codex itself */
    PC_CLOSE_DISCONNECT = 5,
    PC_CLOSE_FAILED = 6,    /* the decision could not be delivered to Codex */
    PC_CLOSE_STALE = 7,     /* id not current: nothing was decided */
    PC_CLOSE_HIDDEN = 8     /* session switched away; still pending on the Mac */
};

enum { PC_ACT_CONTINUE = 0, PC_ACT_SUMMARIZE = 1, PC_ACT_TESTS = 2, PC_ACT_ERRORS = 3, PC_ACT_INTERRUPT = 4, PC_ACT_COUNT = 5 };
enum { PC_ACT_SESSION_PREV = 0x10, PC_ACT_SESSION_NEXT = 0x11 };
enum { PC_ACK_ACCEPTED = 1, PC_ACK_DONE = 2, PC_ACK_FAILED = 3, PC_ACK_UNAVAILABLE = 4 };

enum {
    PC_BTN_UP = 1 << 0,
    PC_BTN_DOWN = 1 << 1,
    PC_BTN_LEFT = 1 << 2,
    PC_BTN_RIGHT = 1 << 3,
    PC_BTN_CROSS = 1 << 4,
    PC_BTN_CIRCLE = 1 << 5,
    PC_BTN_SQUARE = 1 << 6,
    PC_BTN_TRIANGLE = 1 << 7,
    PC_BTN_START = 1 << 8,
    PC_BTN_SELECT = 1 << 9,
    PC_BTN_L = 1 << 10,
    PC_BTN_R = 1 << 11
};

/* ---- bounds-checked reader ------------------------------------------- */
typedef struct {
    const uint8_t *p;
    uint32_t n, off;
    int bad;
} pc_rd_t;

static inline void pc_rd_init(pc_rd_t *r, const uint8_t *p, uint32_t n) {
    r->p = p;
    r->n = n;
    r->off = 0;
    r->bad = 0;
}
static inline uint8_t pc_rd_u8(pc_rd_t *r) {
    if (r->bad || r->off >= r->n) {
        r->bad = 1;
        return 0;
    }
    return r->p[r->off++];
}
static inline uint16_t pc_rd_u16(pc_rd_t *r) {
    uint16_t a = pc_rd_u8(r);
    return (uint16_t)(a | ((uint16_t)pc_rd_u8(r) << 8));
}
static inline uint32_t pc_rd_u32(pc_rd_t *r) {
    uint32_t a = pc_rd_u16(r);
    return a | ((uint32_t)pc_rd_u16(r) << 16);
}
/* Copies a str into out (always terminated, truncated to cap-1). Non-printable bytes become '?'. */
static inline void pc_rd_str(pc_rd_t *r, char *out, uint32_t cap) {
    uint32_t len = pc_rd_u8(r), i, w = 0;
    if (!r->bad && len > r->n - r->off) r->bad = 1;
    if (r->bad) {
        if (cap) out[0] = 0;
        return;
    }
    for (i = 0; i < len; i++) {
        uint8_t c = r->p[r->off + i];
        if (w + 1 < cap) out[w++] = (c >= 0x20 && c < 0x7F) ? (char)c : '?';
    }
    r->off += len;
    if (cap) out[w] = 0;
}

#ifdef __cplusplus
}
#endif
#endif
