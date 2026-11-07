#include "io_mailbox.h"

#ifdef __psp__
#include <pspiofilemgr.h>
#include <pspthreadman.h>
static void mbox_sleep_us(int us) { sceKernelDelayThread(us); }
static uint32_t mbox_boot_id(void) { return sceKernelGetSystemTimeLow() | 1u; }
int psp_is_emulator(void) {
    uint32_t out = 0;
    int r = sceIoDevctl("emulator:", 3 /* EMULATOR_DEVCTL__IS_EMULATOR */, NULL, 0, &out, sizeof out);
    return r >= 0 && out == 1;
}
#else
#include <time.h>
#include <unistd.h>
static void mbox_sleep_us(int us) { usleep((useconds_t)us); }
static uint32_t mbox_boot_id(void) { return (uint32_t)clock() ^ (uint32_t)time(NULL) ^ 1u; }
int psp_is_emulator(void) { return 0; }
#endif

int psp_mbox_init(psp_mbox_t *mb, void *mem, uint32_t size, uint32_t m2p_cap, uint32_t p2m_cap) {
    psp_mbox_hdr_t *h = (psp_mbox_hdr_t *)mem;
    if (((uintptr_t)mem & 63u) || size < PSP_MBOX_HDR_SIZE + m2p_cap + p2m_cap || !m2p_cap || !p2m_cap) return -1;
    memset(mem, 0, PSP_MBOX_HDR_SIZE);
    h->self = (uint32_t)(uintptr_t)mem;
    h->version = 1;
    h->m2p_cap = m2p_cap;
    h->p2m_cap = p2m_cap;
    h->boot_id = mbox_boot_id();
    mb->hdr = h;
    mb->m2p = (uint8_t *)mem + PSP_MBOX_HDR_SIZE;
    mb->p2m = mb->m2p + m2p_cap;
    mb->write_timeout_us = 2000000;
    /* magic last, so a half-initialised header is never matched */
    memcpy(h->magic, PSP_MBOX_MAGIC, 16);
    return 0;
}

int psp_mbox_bridge_seen(const psp_mbox_t *mb) { return mb->hdr->bridge_beat != 0; }

static uint32_t ring_put(uint8_t *ring, uint32_t cap, uint32_t head, const uint8_t *d, uint32_t n) {
    uint32_t i;
    for (i = 0; i < n; i++) ring[(head + i) % cap] = d[i];
    return n;
}
static uint32_t ring_get(const uint8_t *ring, uint32_t cap, uint32_t tail, uint8_t *d, uint32_t n) {
    uint32_t i;
    for (i = 0; i < n; i++) d[i] = ring[(tail + i) % cap];
    return n;
}

static int mbox_write(void *ctx, const void *buf, int len) {
    psp_mbox_t *mb = (psp_mbox_t *)ctx;
    psp_mbox_hdr_t *h = mb->hdr;
    const uint8_t *d = (const uint8_t *)buf;
    int done = 0, waited = 0;
    h->psp_beat++;
    while (done < len) {
        uint32_t used = h->p2m_head - h->p2m_tail;
        uint32_t room = h->p2m_cap - used, n = (uint32_t)(len - done);
        if (room == 0) {
            if (waited >= mb->write_timeout_us) return -1;
            mbox_sleep_us(1000);
            waited += 1000;
            continue;
        }
        if (n > room) n = room;
        ring_put(mb->p2m, h->p2m_cap, h->p2m_head, d + done, n);
        h->p2m_head += n; /* publish after data */
        done += (int)n;
    }
    return done;
}

static int mbox_read(void *ctx, void *buf, int len, int timeout_us) {
    psp_mbox_t *mb = (psp_mbox_t *)ctx;
    psp_mbox_hdr_t *h = mb->hdr;
    int waited = 0;
    h->psp_beat++;
    for (;;) {
        uint32_t avail = h->m2p_head - h->m2p_tail;
        if (avail) {
            uint32_t n = avail < (uint32_t)len ? avail : (uint32_t)len;
            ring_get(mb->m2p, h->m2p_cap, h->m2p_tail, (uint8_t *)buf, n);
            h->m2p_tail += n;
            return (int)n;
        }
        if (timeout_us >= 0 && waited >= timeout_us) return 0;
        mbox_sleep_us(500);
        waited += 500;
    }
}

psp_link_io_t psp_mbox_io(psp_mbox_t *mb) {
    psp_link_io_t io;
    io.write = mbox_write;
    io.read = mbox_read;
    io.ctx = mb;
    return io;
}

uint32_t psp_mbox_peer_write(psp_mbox_t *mb, const uint8_t *d, uint32_t n) {
    psp_mbox_hdr_t *h = mb->hdr;
    uint32_t room = h->m2p_cap - (h->m2p_head - h->m2p_tail);
    if (n > room) n = room;
    ring_put(mb->m2p, h->m2p_cap, h->m2p_head, d, n);
    h->m2p_head += n;
    h->bridge_beat++;
    return n;
}

uint32_t psp_mbox_peer_read(psp_mbox_t *mb, uint8_t *d, uint32_t n) {
    psp_mbox_hdr_t *h = mb->hdr;
    uint32_t avail = h->p2m_head - h->p2m_tail;
    if (n > avail) n = avail;
    ring_get(mb->p2m, h->p2m_cap, h->p2m_tail, d, n);
    h->p2m_tail += n;
    h->bridge_beat++;
    return n;
}
