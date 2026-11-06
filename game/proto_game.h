/*
 * proto_game.h — "Blackwater Ping" game messages (track C, feat/dual-screen-game).
 *
 * Rides on the shared framed protocol (common/protocol/psp_link.h). Message types live in this
 * track's range 0x70-0x9F. Payloads are fixed-size little-endian structs, packed/unpacked by hand
 * (no struct punning, so it is endian/alignment safe on PSP MIPS and macOS arm64).
 * Python mirror: game/mac/bw_proto.py — keep in sync (game/tests checks sizes + golden bytes).
 *
 * Angles: u16, 0..65535 = 0..360 deg, clockwise from world "north" (screen up, -y).
 * Distances: u16 world units (1 unit = 1 Mac pixel at 1x zoom).
 */
#ifndef BW_PROTO_GAME_H
#define BW_PROTO_GAME_H

#include <stdint.h>
#include "../common/protocol/psp_link.h"

#define BW_APP_ID 3 /* PSP_LINK hello app id "game" */
#define BW_PROTO_VERSION 1

enum {
    /* Mac -> PSP */
    BW_T_GAME_START = 0x70,  /* level u8, mode u8, seed u32, max_range u16                       8 B */
    BW_T_SUB_STATE = 0x71,   /* tick u16, x i16, y i16, heading u16, speed u8, hull u8,
                                battery u8, noise u8, flags u8, gates_open u8                    14 B */
    BW_T_ECHO = 0x72,        /* ping_id u8, mode u8, n u8, pad u8, n x contact(6 B)        4+6n B */
    BW_T_HACK_REQ = 0x73,    /* gate_id u8, puzzle u8, difficulty u8, pad u8, seed u32,
                                time_limit_ds u16                                               10 B */
    BW_T_EVENT = 0x74,       /* code u8, pad u8, arg u16                                         4 B */
    /* PSP -> Mac */
    BW_T_PING_CMD = 0x80,    /* ping_id u8, mode u8, bearing u16, width u16                      6 B */
    BW_T_HACK_RESULT = 0x81, /* gate_id u8, ok u8, elapsed_ds u16                                4 B */
    BW_T_MARK = 0x82,        /* ping_id u8, index u8, tag u8, pad u8                             4 B */
    BW_T_PILOT = 0x83,       /* ax i8, ay i8, buttons u16                                        4 B */
    BW_T_READY = 0x84        /* want u8 (1 = start / restart), pad u8, version u16               4 B */
};

enum { BW_SZ_GAME_START = 8, BW_SZ_SUB_STATE = 14, BW_SZ_ECHO_HDR = 4, BW_SZ_CONTACT = 6, BW_SZ_HACK_REQ = 10,
       BW_SZ_EVENT = 4, BW_SZ_PING_CMD = 6, BW_SZ_HACK_RESULT = 4, BW_SZ_MARK = 4, BW_SZ_PILOT = 4, BW_SZ_READY = 4 };

#define BW_ECHO_MAX 24 /* contacts per ECHO -> max payload 148 B */

enum { BW_MODE_COOP = 0, BW_MODE_SOLO = 1 };
enum { BW_PING_PASSIVE = 0, BW_PING_ACTIVE = 1 };
enum { BW_K_ROCK = 0, BW_K_MINE = 1, BW_K_CREATURE = 2, BW_K_GATE = 3, BW_K_EXIT = 4, BW_K_UNKNOWN = 5 };
enum { BW_EV_DAMAGE = 1, BW_EV_CREATURE_NEAR = 2, BW_EV_GATE_OPEN = 3, BW_EV_WIN = 4, BW_EV_LOSE = 5,
       BW_EV_BATTERY_LOW = 6, BW_EV_HACK_FAIL = 7, BW_EV_MARKED = 8 };
/* SUB_STATE.flags */
enum { BW_SF_AT_GATE = 1, BW_SF_HACKING = 2, BW_SF_HUNTED = 4, BW_SF_RUNNING = 8 };
/* abstract buttons (PILOT.buttons and console input) */
enum {
    BW_B_UP = 1 << 0, BW_B_DOWN = 1 << 1, BW_B_LEFT = 1 << 2, BW_B_RIGHT = 1 << 3,
    BW_B_CROSS = 1 << 4, BW_B_CIRCLE = 1 << 5, BW_B_SQUARE = 1 << 6, BW_B_TRIANGLE = 1 << 7,
    BW_B_START = 1 << 8, BW_B_SELECT = 1 << 9, BW_B_L = 1 << 10, BW_B_R = 1 << 11
};

typedef struct { uint8_t level, mode; uint32_t seed; uint16_t max_range; } bw_game_start_t;
typedef struct {
    uint16_t tick; int16_t x, y; uint16_t heading;
    uint8_t speed, hull, battery, noise, flags, gates_open;
} bw_sub_state_t;
typedef struct { uint16_t bearing, range; uint8_t kind, strength; } bw_contact_wire_t;
typedef struct { uint8_t ping_id, mode, n; bw_contact_wire_t c[BW_ECHO_MAX]; } bw_echo_t;
typedef struct { uint8_t gate_id, puzzle, difficulty; uint32_t seed; uint16_t time_limit_ds; } bw_hack_req_t;
typedef struct { uint8_t code; uint16_t arg; } bw_event_t;
typedef struct { uint8_t ping_id, mode; uint16_t bearing, width; } bw_ping_cmd_t;
typedef struct { uint8_t gate_id, ok; uint16_t elapsed_ds; } bw_hack_result_t;
typedef struct { uint8_t ping_id, index, tag; } bw_mark_t;
typedef struct { int8_t ax, ay; uint16_t buttons; } bw_pilot_t;

/* ---- pack (return payload size) ---------------------------------------- */
static inline uint32_t bw_pack_game_start(uint8_t *p, const bw_game_start_t *m) {
    p[0] = m->level; p[1] = m->mode; psp_link_put_u32(p + 2, m->seed); psp_link_put_u16(p + 6, m->max_range);
    return BW_SZ_GAME_START;
}
static inline uint32_t bw_pack_sub_state(uint8_t *p, const bw_sub_state_t *m) {
    psp_link_put_u16(p, m->tick); psp_link_put_u16(p + 2, (uint16_t)m->x); psp_link_put_u16(p + 4, (uint16_t)m->y);
    psp_link_put_u16(p + 6, m->heading);
    p[8] = m->speed; p[9] = m->hull; p[10] = m->battery; p[11] = m->noise; p[12] = m->flags; p[13] = m->gates_open;
    return BW_SZ_SUB_STATE;
}
static inline uint32_t bw_pack_echo(uint8_t *p, const bw_echo_t *m) {
    uint32_t i, n = m->n > BW_ECHO_MAX ? BW_ECHO_MAX : m->n;
    p[0] = m->ping_id; p[1] = m->mode; p[2] = (uint8_t)n; p[3] = 0;
    for (i = 0; i < n; i++) {
        uint8_t *q = p + BW_SZ_ECHO_HDR + i * BW_SZ_CONTACT;
        psp_link_put_u16(q, m->c[i].bearing); psp_link_put_u16(q + 2, m->c[i].range);
        q[4] = m->c[i].kind; q[5] = m->c[i].strength;
    }
    return BW_SZ_ECHO_HDR + n * BW_SZ_CONTACT;
}
static inline uint32_t bw_pack_hack_req(uint8_t *p, const bw_hack_req_t *m) {
    p[0] = m->gate_id; p[1] = m->puzzle; p[2] = m->difficulty; p[3] = 0;
    psp_link_put_u32(p + 4, m->seed); psp_link_put_u16(p + 8, m->time_limit_ds);
    return BW_SZ_HACK_REQ;
}
static inline uint32_t bw_pack_event(uint8_t *p, const bw_event_t *m) {
    p[0] = m->code; p[1] = 0; psp_link_put_u16(p + 2, m->arg);
    return BW_SZ_EVENT;
}
static inline uint32_t bw_pack_ping_cmd(uint8_t *p, const bw_ping_cmd_t *m) {
    p[0] = m->ping_id; p[1] = m->mode; psp_link_put_u16(p + 2, m->bearing); psp_link_put_u16(p + 4, m->width);
    return BW_SZ_PING_CMD;
}
static inline uint32_t bw_pack_hack_result(uint8_t *p, const bw_hack_result_t *m) {
    p[0] = m->gate_id; p[1] = m->ok; psp_link_put_u16(p + 2, m->elapsed_ds);
    return BW_SZ_HACK_RESULT;
}
static inline uint32_t bw_pack_mark(uint8_t *p, const bw_mark_t *m) {
    p[0] = m->ping_id; p[1] = m->index; p[2] = m->tag; p[3] = 0;
    return BW_SZ_MARK;
}
static inline uint32_t bw_pack_pilot(uint8_t *p, const bw_pilot_t *m) {
    p[0] = (uint8_t)m->ax; p[1] = (uint8_t)m->ay; psp_link_put_u16(p + 2, m->buttons);
    return BW_SZ_PILOT;
}
static inline uint32_t bw_pack_ready(uint8_t *p, uint8_t want) {
    p[0] = want; p[1] = 0; psp_link_put_u16(p + 2, BW_PROTO_VERSION);
    return BW_SZ_READY;
}

/* ---- unpack (return 0 on success, -1 if the payload is too short) ------ */
static inline int bw_unpack_game_start(const uint8_t *p, uint32_t n, bw_game_start_t *m) {
    if (n < BW_SZ_GAME_START) return -1;
    m->level = p[0]; m->mode = p[1]; m->seed = psp_link_get_u32(p + 2); m->max_range = psp_link_get_u16(p + 6);
    return 0;
}
static inline int bw_unpack_sub_state(const uint8_t *p, uint32_t n, bw_sub_state_t *m) {
    if (n < BW_SZ_SUB_STATE) return -1;
    m->tick = psp_link_get_u16(p); m->x = (int16_t)psp_link_get_u16(p + 2); m->y = (int16_t)psp_link_get_u16(p + 4);
    m->heading = psp_link_get_u16(p + 6);
    m->speed = p[8]; m->hull = p[9]; m->battery = p[10]; m->noise = p[11]; m->flags = p[12]; m->gates_open = p[13];
    return 0;
}
static inline int bw_unpack_echo(const uint8_t *p, uint32_t n, bw_echo_t *m) {
    uint32_t i, k;
    if (n < BW_SZ_ECHO_HDR) return -1;
    m->ping_id = p[0]; m->mode = p[1]; k = p[2];
    if (k > BW_ECHO_MAX) k = BW_ECHO_MAX;
    if (n < BW_SZ_ECHO_HDR + k * BW_SZ_CONTACT) return -1;
    m->n = (uint8_t)k;
    for (i = 0; i < k; i++) {
        const uint8_t *q = p + BW_SZ_ECHO_HDR + i * BW_SZ_CONTACT;
        m->c[i].bearing = psp_link_get_u16(q); m->c[i].range = psp_link_get_u16(q + 2);
        m->c[i].kind = q[4]; m->c[i].strength = q[5];
    }
    return 0;
}
static inline int bw_unpack_hack_req(const uint8_t *p, uint32_t n, bw_hack_req_t *m) {
    if (n < BW_SZ_HACK_REQ) return -1;
    m->gate_id = p[0]; m->puzzle = p[1]; m->difficulty = p[2];
    m->seed = psp_link_get_u32(p + 4); m->time_limit_ds = psp_link_get_u16(p + 8);
    return 0;
}
static inline int bw_unpack_event(const uint8_t *p, uint32_t n, bw_event_t *m) {
    if (n < BW_SZ_EVENT) return -1;
    m->code = p[0]; m->arg = psp_link_get_u16(p + 2);
    return 0;
}

/* Shared deterministic PRNG (xorshift32), mirrored in Python for puzzle generation. */
static inline uint32_t bw_rng_next(uint32_t *s) {
    uint32_t x = *s ? *s : 0x9E3779B9u;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *s = x;
    return x;
}

#endif
