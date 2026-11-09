/* gfx.h — small anti-aliased software renderer into a 32-bit framebuffer (PSP 8888 = 0xAABBGGRR).
 * Plain C: the same code runs on the PSP and in the macOS host build (companion/psp/host). */
#ifndef PC_GFX_H
#define PC_GFX_H
#include <stdint.h>

#define GFX_W 480
#define GFX_H 272
#define GFX_STRIDE 512

#define GFX_RGBA(r, g, b, a) (((uint32_t)(a) << 24) | ((uint32_t)(b) << 16) | ((uint32_t)(g) << 8) | (uint32_t)(r))
#define GFX_RGB(r, g, b) GFX_RGBA(r, g, b, 255)

typedef struct {
    float x, y;
} vec2_t;

typedef struct {
    uint16_t off;
    uint8_t w, h;
    int8_t xo, yo;
    uint8_t adv;
} font_glyph_t;

typedef struct {
    const font_glyph_t *glyphs;
    const unsigned char *data;
    uint8_t line_h, ascent;
} font_t;

extern const font_t *const gfx_font_small, *const gfx_font_body, *const gfx_font_title;

void gfx_begin(uint32_t *px);
void gfx_clear_vgrad(uint32_t top, uint32_t bottom);

/* Paths: add closed polygons (same winding = union, opposite winding = hole), then fill once. */
void gfx_path_add(const vec2_t *p, int n);
void gfx_path_fill(uint32_t color);
void gfx_path_fill_vgrad(uint32_t top, uint32_t bottom, float y0, float y1);

void gfx_ellipse(float cx, float cy, float rx, float ry, uint32_t color);
void gfx_capsule_add(float x0, float y0, float x1, float y1, float r);
void gfx_stroke(const vec2_t *p, int n, float width, uint32_t color);
void gfx_rrect(float x, float y, float w, float h, float r, uint32_t color);
void gfx_ring(float cx, float cy, float r, float width, float a0, float a1, uint32_t color);

int gfx_text_width(const font_t *f, const char *s);
/* x = left edge, y = top of the line box. */
void gfx_text(const font_t *f, int x, int y, const char *s, uint32_t color);
void gfx_text_center(const font_t *f, int cx, int y, const char *s, uint32_t color);
/* Copies s into out, cut with "..." so that it fits max_w pixels. */
void gfx_fit_text(const font_t *f, const char *s, int max_w, char *out, int cap);
#endif
