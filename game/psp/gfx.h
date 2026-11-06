/* gfx.h — tiny software renderer into a 32-bit framebuffer (PSP 8888 = 0xAABBGGRR in memory).
 * Plain C, no deps: the same drawing code runs on the PSP and in the macOS host build (PNG dumps). */
#ifndef BW_GFX_H
#define BW_GFX_H
#include <stdint.h>

#define BW_SCREEN_W 480
#define BW_SCREEN_H 272
#define BW_STRIDE 512

/* PSP framebuffer byte order: R, G, B, A -> as little-endian u32 0xAABBGGRR */
#define BW_RGB(r, g, b) (0xFF000000u | ((uint32_t)(b) << 16) | ((uint32_t)(g) << 8) | (uint32_t)(r))

typedef struct {
    uint32_t *px; /* BW_STRIDE * BW_SCREEN_H pixels */
} bw_gfx_t;

uint32_t bw_scale_color(uint32_t c, int num, int den); /* brightness num/den */
void bw_clear(bw_gfx_t *g, uint32_t c);
void bw_pixel(bw_gfx_t *g, int x, int y, uint32_t c);
void bw_fill_rect(bw_gfx_t *g, int x, int y, int w, int h, uint32_t c);
void bw_rect(bw_gfx_t *g, int x, int y, int w, int h, uint32_t c);
void bw_line(bw_gfx_t *g, int x0, int y0, int x1, int y1, uint32_t c);
void bw_circle(bw_gfx_t *g, int cx, int cy, int r, uint32_t c);
void bw_fill_circle(bw_gfx_t *g, int cx, int cy, int r, uint32_t c);
/* 5x7 font in 6x8 cells, uppercase ASCII 0x20-0x5F (lowercase is folded to upper). Returns end x. */
int bw_text(bw_gfx_t *g, int x, int y, const char *s, uint32_t c, int scale);
#endif
