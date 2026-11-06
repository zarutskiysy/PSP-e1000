/*
 * io_mailbox.h — emulator transport: two byte rings in PSP RAM that tools/ppsspp_bridge.py reads
 * and writes through PPSSPP's WebSocket debugger (memory.read / memory.write), bridging the PSP app
 * running in PPSSPP to the normal Mac mock TCP port. PPSSPP cannot emulate USB to the host, so this
 * is how the real PSP code is tested end-to-end against the real Mac code tonight.
 *
 * Layout (little-endian, 64-byte header, then m2p ring, then p2m ring):
 *   0  magic[16] "PSPMACLINK/MBOX1"
 *  16  self      PSP address of this header (bridge verifies it == where it found the magic)
 *  20  version   1
 *  24  m2p_cap   Mac->PSP ring size
 *  28  p2m_cap   PSP->Mac ring size
 *  32  m2p_head  total bytes written by the Mac   (bridge writes)
 *  36  m2p_tail  total bytes consumed by the PSP  (PSP writes)
 *  40  p2m_head  total bytes written by the PSP   (PSP writes)
 *  44  p2m_tail  total bytes consumed by the Mac  (bridge writes)
 *  48  bridge_beat  incremented by the bridge every poll (0 = no bridge seen yet)
 *  52  psp_beat     incremented by the PSP on every io call
 *  56  reserved[2]
 * Counters are free-running u32; ring index = counter % cap.
 *
 * Never use on real hardware (nothing would read it). Pick it when psp_is_emulator() is true.
 */
#ifndef PSP_IO_MAILBOX_H
#define PSP_IO_MAILBOX_H
#include "link.h"

#define PSP_MBOX_MAGIC "PSPMACLINK/MBOX1"
#define PSP_MBOX_HDR_SIZE 64u

typedef struct {
    uint8_t magic[16];
    uint32_t self;
    uint32_t version;
    uint32_t m2p_cap;
    uint32_t p2m_cap;
    volatile uint32_t m2p_head;
    volatile uint32_t m2p_tail;
    volatile uint32_t p2m_head;
    volatile uint32_t p2m_tail;
    volatile uint32_t bridge_beat;
    volatile uint32_t psp_beat;
    uint32_t reserved[2];
} psp_mbox_hdr_t;

typedef struct {
    psp_mbox_hdr_t *hdr;
    uint8_t *m2p;
    uint8_t *p2m;
    int write_timeout_us; /* how long write() waits for ring space (default 2 s) */
} psp_mbox_t;

/* mem must be 64-byte aligned, size >= 64 + m2p_cap + p2m_cap. Typical: 64 KiB each way.
 * Use a static buffer: static uint8_t mb[64 + 2*65536] __attribute__((aligned(64))); */
int psp_mbox_init(psp_mbox_t *mb, void *mem, uint32_t size, uint32_t m2p_cap, uint32_t p2m_cap);
psp_link_io_t psp_mbox_io(psp_mbox_t *mb);
/* 1 once the bridge has polled at least once. */
int psp_mbox_bridge_seen(const psp_mbox_t *mb);

/* "Peer" side (what the bridge does), for host unit tests only. */
uint32_t psp_mbox_peer_write(psp_mbox_t *mb, const uint8_t *d, uint32_t n);
uint32_t psp_mbox_peer_read(psp_mbox_t *mb, uint8_t *d, uint32_t n);

/* 1 when running in PPSSPP (sceIoDevctl("emulator:", 3 = IS_EMULATOR)); always 0 on host builds. */
int psp_is_emulator(void);
#endif
