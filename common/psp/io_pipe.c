#include "io_pipe.h"

void psp_ring_init(psp_ring_t *r, uint8_t *buf, uint32_t cap) {
    r->buf = buf;
    r->cap = cap;
    r->head = r->tail = r->count = 0;
}

uint32_t psp_ring_write(psp_ring_t *r, const uint8_t *d, uint32_t n) {
    uint32_t i;
    if (n > r->cap - r->count) n = r->cap - r->count;
    for (i = 0; i < n; i++) {
        r->buf[r->head] = d[i];
        r->head = (r->head + 1) % r->cap;
    }
    r->count += n;
    return n;
}

uint32_t psp_ring_read(psp_ring_t *r, uint8_t *d, uint32_t n) {
    uint32_t i;
    if (n > r->count) n = r->count;
    for (i = 0; i < n; i++) {
        d[i] = r->buf[r->tail];
        r->tail = (r->tail + 1) % r->cap;
    }
    r->count -= n;
    return n;
}

static int pipe_write(void *ctx, const void *buf, int len) {
    psp_pipe_end_t *e = (psp_pipe_end_t *)ctx;
    if ((uint32_t)len > e->out->cap - e->out->count) return -1;
    return (int)psp_ring_write(e->out, (const uint8_t *)buf, (uint32_t)len);
}

static int pipe_read(void *ctx, void *buf, int len, int timeout_us) {
    psp_pipe_end_t *e = (psp_pipe_end_t *)ctx;
    (void)timeout_us;
    return (int)psp_ring_read(e->in, (uint8_t *)buf, (uint32_t)len);
}

psp_link_io_t psp_pipe_io(psp_pipe_end_t *end) {
    psp_link_io_t io;
    io.write = pipe_write;
    io.read = pipe_read;
    io.ctx = end;
    return io;
}
