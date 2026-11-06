/*
 * proto_screen.h — feat/second-screen message types (range 0x40-0x6F) on top of
 * common/protocol/psp_link.h. Python mirror: screen/mac/proto_screen.py (keep in sync;
 * screen/tests/test_proto_sync.py checks the constants).
 *
 * Screen: 480x272, PSP 16-bit 565 pixel order (R in the LOW 5 bits: v = B<<11 | G<<5 | R),
 * cut into 16x16 tiles: 30 x 17 = 510 tiles, tile index = ty * 30 + tx.
 *
 * SCR_CHUNK (Mac -> PSP), payload <= 64 KiB, little-endian:
 *   off size
 *   0   4    frame_id      increments per frame (wraps)
 *   4   2    chunk_idx     0,1,2... within the frame
 *   6   2    n_items       tile records in the body
 *   8   1    codec         SCR_CODEC_RAW | SCR_CODEC_LZ4
 *   9   1    cflags        SCR_CF_KEY (frame carries every tile) | SCR_CF_LAST (last chunk of frame)
 *   10  2    reserved      0
 *   12  4    body_len      uncompressed body length (<= SCR_MAX_BODY)
 *   16  ...  body          raw records, or one LZ4 *block* (no frame header) that inflates to body_len
 * Body = n_items records:
 *   u16 tag   bits 0..11 tile index, bit 15 SCR_TAG_SOLID
 *   SOLID:    u16 color                         (whole tile one colour)
 *   else:     256 x u16 pixels, row-major 16x16
 * Tiles carry absolute pixels, so a lost chunk only leaves stale tiles; the PSP then sets
 * SCR_ACKF_NEED_KEY and the Mac sends a keyframe.
 *
 * SCR_ACK (PSP -> Mac) after the LAST chunk of a frame was decoded and presented (32 bytes):
 *   0 u32 frame_id, 4 u32 decode_us, 8 u32 present_us, 12 u32 frames_shown, 16 u32 rx_bytes,
 *   20 u32 buttons, 24 u16 fps_x10, 26 u16 ack_flags, 28 u32 decode_errors
 *
 * Throughput probe:
 *   SCR_PROBE_DATA   (Mac -> PSP) any payload, counted and dropped
 *   SCR_PROBE_END    (Mac -> PSP) u32 tag
 *   SCR_PROBE_RESULT (PSP -> Mac) u32 tag, u32 bytes, u32 frames, u32 us (first->last DATA), u32 crc_errors
 *   SCR_PROBE_RESET  (Mac -> PSP) empty: zero the counters
 */
#ifndef PROTO_SCREEN_H
#define PROTO_SCREEN_H

#include <stdint.h>

#define SCR_W 480
#define SCR_H 272
#define SCR_TILE 16
#define SCR_TILES_X (SCR_W / SCR_TILE) /* 30 */
#define SCR_TILES_Y (SCR_H / SCR_TILE) /* 17 */
#define SCR_NTILES (SCR_TILES_X * SCR_TILES_Y) /* 510 */
#define SCR_TILE_BYTES (SCR_TILE * SCR_TILE * 2) /* 512 */

#define SCR_MAX_PAYLOAD 65536u /* one SCR_CHUNK payload, header included */
#define SCR_CHUNK_HDR 16u
#define SCR_MAX_BODY (SCR_MAX_PAYLOAD - SCR_CHUNK_HDR)

enum {
    SCR_T_CHUNK = 0x40,
    SCR_T_ACK = 0x41,
    SCR_T_PROBE_DATA = 0x50,
    SCR_T_PROBE_END = 0x51,
    SCR_T_PROBE_RESULT = 0x52,
    SCR_T_PROBE_RESET = 0x53
};

enum { SCR_CODEC_RAW = 0, SCR_CODEC_LZ4 = 1 };
enum { SCR_CF_KEY = 0x01, SCR_CF_LAST = 0x02 };
#define SCR_TAG_SOLID 0x8000u
#define SCR_TAG_INDEX_MASK 0x0FFFu
enum { SCR_ACKF_NEED_KEY = 0x0001 };
#define SCR_ACK_SIZE 32u
#define SCR_PROBE_RESULT_SIZE 20u

#endif
