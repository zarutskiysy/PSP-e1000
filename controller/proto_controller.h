/*
 * proto_controller.h — feat/mac-controller message types (range 0x10-0x3F) on top of
 * common/protocol/psp_link.h. Python mirror: controller/mac/deck/proto.py (keep in sync;
 * controller/tests/test_proto.py checks the constants and sizes against this file).
 *
 * All payloads are fixed-size, little-endian, no padding surprises (built byte by byte).
 *
 * Session:
 *   PSP boots -> sends HELLO (app=1) and CONFIG_REQ every second until it has a WHEEL_CONFIG.
 *   Mac connects -> sends HELLO every second until it sees HELLO/HELLO_ACK, then WHEEL_CONFIG
 *   and MAC_STATUS. Either side answers PING with PONG (common link code does it).
 *   PSP -> Mac: INPUT_STATE every frame (60 Hz, vblank) — the Mac maps it to mouse/keys.
 *   PSP -> Mac: WHEEL_FIRE when the action wheel is released on a slice.
 *   Mac -> PSP: ACTION_RESULT (text shown on the PSP), MAC_STATUS (RTT etc. shown on the PSP).
 */
#ifndef PROTO_CONTROLLER_H
#define PROTO_CONTROLLER_H

#include "../common/protocol/psp_link.h"

#define CTRL_APP_ID 1u /* HELLO app id for this track */

enum {
    CTRL_T_INPUT_STATE = 0x10,   /* PSP->Mac, CTRL_INPUT_SIZE */
    CTRL_T_WHEEL_CONFIG = 0x11,  /* Mac->PSP, CTRL_WHEEL_CONFIG_SIZE */
    CTRL_T_WHEEL_FIRE = 0x12,    /* PSP->Mac, CTRL_WHEEL_FIRE_SIZE */
    CTRL_T_ACTION_RESULT = 0x13, /* Mac->PSP, CTRL_ACTION_RESULT_SIZE */
    CTRL_T_CONFIG_REQ = 0x14,    /* PSP->Mac, empty: "send me WHEEL_CONFIG" */
    CTRL_T_MAC_STATUS = 0x15     /* Mac->PSP, CTRL_MAC_STATUS_SIZE */
};

/* INPUT_STATE (16 bytes)
 *  0 u32 buttons   PSP_CTRL_* bits as returned by sceCtrlPeekBufferPositive
 *  4 u8  lx        analog X 0..255 (centre ~128)
 *  5 u8  ly        analog Y 0..255 (centre ~128, 0 = up)
 *  6 u8  flags     CTRL_IN_F_*
 *  7 u8  hover     wheel slice under the nub while the wheel is open, 0xFF = none
 *  8 u32 t_us      sceKernelGetSystemTimeLow() at sampling (wraps every ~71 min)
 * 12 u32 frame     PSP frame counter
 */
#define CTRL_INPUT_SIZE 16u
#define CTRL_IN_F_WHEEL_OPEN 0x01u /* Mac must not move the mouse / fire keys from the nub */
#define CTRL_NO_SLICE 0xFFu

/* WHEEL_CONFIG (4 + 8*24 = 196 bytes)
 *  0 u8  count (0..8)   1 u8 version (=1)   2 u16 reserved
 *  4 char label[8][24]  UTF-8/ASCII, NUL-padded (PSP draws ASCII only)
 * Slice 0 is at 12 o'clock, slices go clockwise. */
#define CTRL_WHEEL_MAX 8u
#define CTRL_LABEL_LEN 24u
#define CTRL_WHEEL_CONFIG_SIZE (4u + CTRL_WHEEL_MAX * CTRL_LABEL_LEN)

/* WHEEL_FIRE (8 bytes): 0 u8 slice, 1..3 reserved, 4 u32 t_us */
#define CTRL_WHEEL_FIRE_SIZE 8u

/* ACTION_RESULT (52 bytes): 0 u8 slice, 1 u8 ok (1/0), 2 u16 reserved, 4 char text[48] NUL-padded */
#define CTRL_RESULT_TEXT_LEN 48u
#define CTRL_ACTION_RESULT_SIZE (4u + CTRL_RESULT_TEXT_LEN)

/* MAC_STATUS (16 bytes)
 *  0 u32 rtt_us      last Mac-measured PING RTT (0 = unknown)
 *  4 u32 events      synthetic events posted (or logged in dry-run)
 *  8 u16 input_hz    INPUT_STATE frames/s seen by the Mac (last window)
 * 10 u8  dry_run     1 = Mac only logs events
 * 11 u8  ax_trusted  1 = Accessibility granted
 * 12 u32 reserved */
#define CTRL_MAC_STATUS_SIZE 16u

#endif
