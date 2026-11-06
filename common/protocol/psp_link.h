/*
 * psp_link.h — tiny framed protocol shared by the PSP and the Mac.
 *
 * Header-only, freestanding C99 (only <stdint.h>/<stddef.h>/<string.h>).
 * Compiles with psp-gcc (PSP, little-endian MIPS) and clang (macOS arm64).
 * The Python mirror is common/python/pspmac/protocol.py — keep them in sync;
 * tests/test_golden.py cross-checks both against the same golden vectors.
 *
 * Wire format (all integers little-endian):
 *
 *   off  size  field
 *   0    1     magic0  = 'P' (0x50)
 *   1    1     magic1  = 'L' (0x4C)
 *   2    1     type    (see PSP_LINK_T_*; track-specific ranges below)
 *   3    1     flags   (PSP_LINK_F_*)
 *   4    2     seq     (sender's counter, wraps)
 *   6    4     len     (payload length in bytes)
 *   10   len   payload
 *   10+len 2   crc16   CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over bytes [0, 10+len)
 *
 * Total overhead: 12 bytes per frame.
 */
#ifndef PSP_LINK_H
#define PSP_LINK_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PSP_LINK_MAGIC0 0x50u /* 'P' */
#define PSP_LINK_MAGIC1 0x4Cu /* 'L' */
#define PSP_LINK_HEADER_SIZE 10u
#define PSP_LINK_CRC_SIZE 2u
#define PSP_LINK_OVERHEAD (PSP_LINK_HEADER_SIZE + PSP_LINK_CRC_SIZE)
#define PSP_LINK_VERSION 1u

/* USB identity used by common/psp/usb (PSP kernel PRX) and the Mac libusb transport. */
#define PSP_LINK_USB_VID 0x054Cu /* Sony; filled in by the PSP USB stack */
#define PSP_LINK_USB_PID 0x01CBu /* passed to sceUsbActivate(); psplink uses 0x01C9 */
#define PSP_LINK_USB_EP_IN 0x81u  /* PSP -> Mac */
#define PSP_LINK_USB_EP_OUT 0x02u /* Mac -> PSP */

/* ---- message types ----------------------------------------------------
 * 0x00-0x0F  common (below)
 * 0x10-0x3F  feat/mac-controller
 * 0x40-0x6F  feat/second-screen
 * 0x70-0x9F  feat/dual-screen-game
 * 0xA0-0xEF  future tracks
 * 0xF0-0xFF  reserved / testing
 */
enum {
    PSP_LINK_T_HELLO = 0x01,     /* payload: psp_link_hello_t (+ name bytes) */
    PSP_LINK_T_HELLO_ACK = 0x02, /* payload: psp_link_hello_t (+ name bytes) */
    PSP_LINK_T_PING = 0x03,      /* payload: opaque (usually u64 sender time in us); echoed in PONG */
    PSP_LINK_T_PONG = 0x04,      /* payload: copy of the PING payload */
    PSP_LINK_T_LOG = 0x05,       /* payload: UTF-8 text, no terminator */
    PSP_LINK_T_BYE = 0x06,       /* payload: empty */
    PSP_LINK_T_ERROR = 0x07,     /* payload: u16 code + UTF-8 text */
    PSP_LINK_T_TEST = 0xF0       /* payload: anything (tests / throughput probes) */
};

enum {
    PSP_LINK_F_NONE = 0x00,
    PSP_LINK_F_ACK_REQ = 0x01, /* receiver should ACK (track-defined) */
    PSP_LINK_F_LAST = 0x02     /* last chunk of a multi-frame message (track-defined) */
};

enum { PSP_LINK_ROLE_MAC = 0, PSP_LINK_ROLE_PSP = 1 };

/* HELLO / HELLO_ACK payload prefix (8 bytes), followed by an optional UTF-8 name. */
typedef struct {
    uint16_t version;    /* PSP_LINK_VERSION */
    uint8_t role;        /* PSP_LINK_ROLE_* */
    uint8_t app;         /* track id: 0 generic, 1 controller, 2 screen, 3 game */
    uint32_t max_payload;/* largest payload the sender can receive */
} psp_link_hello_t;

/* ---- little-endian helpers -------------------------------------------- */
static inline void psp_link_put_u16(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}
static inline void psp_link_put_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}
static inline uint16_t psp_link_get_u16(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}
static inline uint32_t psp_link_get_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ---- CRC-16/CCITT-FALSE (table-driven) -------------------------------- */
static const uint16_t psp_link_crc_table[256] = {
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6,
    0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485,
    0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4,
    0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
    0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
    0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12,
    0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
    0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41,
    0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70,
    0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
    0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F,
    0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E,
    0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D,
    0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C,
    0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
    0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A,
    0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9,
    0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
    0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8,
    0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0
};
static inline uint16_t psp_link_crc16_update(uint16_t crc, const uint8_t *data, size_t n) {
    size_t i;
    for (i = 0; i < n; i++) crc = (uint16_t)((crc << 8) ^ psp_link_crc_table[((crc >> 8) ^ data[i]) & 0xFFu]);
    return crc;
}
#define PSP_LINK_CRC_INIT 0xFFFFu
static inline uint16_t psp_link_crc16(const uint8_t *data, size_t n) {
    return psp_link_crc16_update(PSP_LINK_CRC_INIT, data, n);
}

/* ---- encoding ---------------------------------------------------------- */

/* Writes the 10-byte header into out. */
static inline void psp_link_write_header(uint8_t *out, uint8_t type, uint8_t flags, uint16_t seq, uint32_t len) {
    out[0] = PSP_LINK_MAGIC0;
    out[1] = PSP_LINK_MAGIC1;
    out[2] = type;
    out[3] = flags;
    psp_link_put_u16(out + 4, seq);
    psp_link_put_u32(out + 6, len);
}

/* Encodes a whole frame into out. Returns the frame size, or 0 if cap is too small.
 * payload may alias out + PSP_LINK_HEADER_SIZE (zero-copy: fill payload first, then encode). */
static inline size_t psp_link_encode(uint8_t *out, size_t cap, uint8_t type, uint8_t flags, uint16_t seq,
                                     const void *payload, uint32_t len) {
    size_t total = (size_t)len + PSP_LINK_OVERHEAD;
    uint16_t crc;
    if (cap < total) return 0;
    if (len && payload != out + PSP_LINK_HEADER_SIZE) memmove(out + PSP_LINK_HEADER_SIZE, payload, len);
    psp_link_write_header(out, type, flags, seq, len);
    crc = psp_link_crc16(out, PSP_LINK_HEADER_SIZE + (size_t)len);
    psp_link_put_u16(out + PSP_LINK_HEADER_SIZE + len, crc);
    return total;
}

/* ---- streaming parser --------------------------------------------------- */

typedef struct {
    uint8_t type;
    uint8_t flags;
    uint16_t seq;
    uint32_t len;
    const uint8_t *payload; /* points into the parser buffer; valid until the next feed() */
} psp_link_frame_t;

enum { PSP_LINK_S_MAGIC0 = 0, PSP_LINK_S_MAGIC1, PSP_LINK_S_HEADER, PSP_LINK_S_PAYLOAD, PSP_LINK_S_CRC };

typedef struct {
    uint8_t *buf;    /* payload buffer supplied by the caller */
    uint32_t cap;    /* its size == max accepted payload */
    int state;
    uint8_t hdr[PSP_LINK_HEADER_SIZE];
    uint32_t hpos;   /* bytes of header collected */
    uint32_t ppos;   /* bytes of payload collected (or skipped when oversize) */
    uint8_t crcb[2];
    uint32_t cpos;
    uint32_t len;
    int oversize;    /* current frame is larger than cap: it is skipped */
    uint16_t crc;    /* running CRC */
    /* stats */
    uint32_t frames_ok;
    uint32_t crc_errors;
    uint32_t oversize_frames;
    uint32_t junk_bytes; /* bytes dropped while hunting for magic */
} psp_link_parser_t;

static inline void psp_link_parser_init(psp_link_parser_t *p, uint8_t *buf, uint32_t cap) {
    memset(p, 0, sizeof(*p));
    p->buf = buf;
    p->cap = cap;
    p->state = PSP_LINK_S_MAGIC0;
}

static inline void psp_link_parser_reset(psp_link_parser_t *p) {
    p->state = PSP_LINK_S_MAGIC0;
    p->hpos = p->ppos = p->cpos = 0;
    p->oversize = 0;
}

/*
 * Feeds up to n bytes. Returns 1 as soon as one valid frame is complete (filled into *out,
 * *consumed = bytes used so far), 0 when all n bytes were consumed without completing a
 * frame. Call in a loop, advancing data by *consumed, until it returns 0.
 * Frames with a bad CRC or a payload larger than cap are dropped and counted.
 */
static inline int psp_link_parser_feed(psp_link_parser_t *p, const uint8_t *data, size_t n, size_t *consumed,
                                       psp_link_frame_t *out) {
    size_t i = 0;
    while (i < n) {
        uint8_t c = data[i];
        switch (p->state) {
        case PSP_LINK_S_MAGIC0:
            i++;
            if (c == PSP_LINK_MAGIC0) {
                p->hdr[0] = c;
                p->state = PSP_LINK_S_MAGIC1;
            } else {
                p->junk_bytes++;
            }
            break;
        case PSP_LINK_S_MAGIC1:
            if (c == PSP_LINK_MAGIC1) {
                i++;
                p->hdr[1] = c;
                p->hpos = 2;
                p->state = PSP_LINK_S_HEADER;
            } else {
                /* do not consume: c may itself be MAGIC0 */
                p->junk_bytes++;
                p->state = PSP_LINK_S_MAGIC0;
            }
            break;
        case PSP_LINK_S_HEADER: {
            size_t take = PSP_LINK_HEADER_SIZE - p->hpos;
            if (take > n - i) take = n - i;
            memcpy(p->hdr + p->hpos, data + i, take);
            p->hpos += (uint32_t)take;
            i += take;
            if (p->hpos == PSP_LINK_HEADER_SIZE) {
                p->len = psp_link_get_u32(p->hdr + 6);
                p->crc = psp_link_crc16(p->hdr, PSP_LINK_HEADER_SIZE);
                p->ppos = 0;
                p->cpos = 0;
                p->oversize = p->len > p->cap;
                p->state = p->len ? PSP_LINK_S_PAYLOAD : PSP_LINK_S_CRC;
            }
            break;
        }
        case PSP_LINK_S_PAYLOAD: {
            size_t take = p->len - p->ppos;
            if (take > n - i) take = n - i;
            if (!p->oversize) {
                memcpy(p->buf + p->ppos, data + i, take);
                p->crc = psp_link_crc16_update(p->crc, data + i, take);
            }
            p->ppos += (uint32_t)take;
            i += take;
            if (p->ppos == p->len) p->state = PSP_LINK_S_CRC;
            break;
        }
        case PSP_LINK_S_CRC:
            p->crcb[p->cpos++] = c;
            i++;
            if (p->cpos == 2) {
                uint16_t got = psp_link_get_u16(p->crcb);
                int ok = !p->oversize && got == p->crc;
                if (p->oversize)
                    p->oversize_frames++;
                else if (!ok)
                    p->crc_errors++;
                p->state = PSP_LINK_S_MAGIC0;
                if (ok) {
                    p->frames_ok++;
                    out->type = p->hdr[2];
                    out->flags = p->hdr[3];
                    out->seq = psp_link_get_u16(p->hdr + 4);
                    out->len = p->len;
                    out->payload = p->buf;
                    *consumed = i;
                    return 1;
                }
            }
            break;
        default:
            psp_link_parser_reset(p);
            break;
        }
    }
    *consumed = i;
    return 0;
}

#ifdef __cplusplus
}
#endif

#endif /* PSP_LINK_H */
