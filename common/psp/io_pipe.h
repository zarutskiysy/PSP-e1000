/* io_pipe.h — in-memory byte pipe pair (no threads). Used by unit tests and by PSP apps in
 * emulator "demo" mode, where a scripted fake Mac lives in the same process. */
#ifndef PSP_IO_PIPE_H
#define PSP_IO_PIPE_H
#include "link.h"

typedef struct {
    uint8_t *buf;
    uint32_t cap, head, tail, count;
} psp_ring_t;

void psp_ring_init(psp_ring_t *r, uint8_t *buf, uint32_t cap);
uint32_t psp_ring_write(psp_ring_t *r, const uint8_t *d, uint32_t n);
uint32_t psp_ring_read(psp_ring_t *r, uint8_t *d, uint32_t n);

/* One end of a duplex pipe: writes go to `out`, reads come from `in`. */
typedef struct {
    psp_ring_t *in, *out;
} psp_pipe_end_t;

/* read() never blocks (timeouts are ignored): returns 0 when empty. write() returns -1 if full. */
psp_link_io_t psp_pipe_io(psp_pipe_end_t *end);
#endif
