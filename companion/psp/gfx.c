/* gfx.c — exact-area coverage rasteriser (signed-area accumulation, as in font-rs) + alpha text.
 * Shapes are polygons; edges add signed area into g_acc, a fill integrates each row of the path's
 * bounding box and clears it again, so cost is proportional to what is drawn. */
#include "gfx.h"

#include <math.h>
#include <string.h>

#include "font_data.h"

#define ROW (GFX_W + 3)

const font_t *const gfx_font_small = &font_small, *const gfx_font_body = &font_body, *const gfx_font_title = &font_title;

static float g_acc[ROW * GFX_H];
static uint32_t *g_px;
static int g_y0 = GFX_H, g_y1 = -1;
static short g_row_x0[GFX_H], g_row_x1[GFX_H]; /* touched cells per row: a fill visits nothing else */
static int g_rows_ready;

static void reset_rows(void) {
    int y;
    for (y = 0; y < GFX_H; y++) {
        g_row_x0[y] = ROW;
        g_row_x1[y] = -1;
    }
    g_rows_ready = 1;
}

void gfx_begin(uint32_t *px) {
    g_px = px;
    if (!g_rows_ready) reset_rows();
}

static inline uint32_t lerp_rgb(uint32_t a, uint32_t b, int t256) {
    uint32_t rb = (((a & 0xFF00FFu) * (uint32_t)(256 - t256) + (b & 0xFF00FFu) * (uint32_t)t256) >> 8) & 0xFF00FFu;
    uint32_t g = (((a & 0x00FF00u) * (uint32_t)(256 - t256) + (b & 0x00FF00u) * (uint32_t)t256) >> 8) & 0x00FF00u;
    return rb | g;
}

void gfx_clear_vgrad(uint32_t top, uint32_t bottom) {
    int y, x;
    for (y = 0; y < GFX_H; y++) {
        uint32_t c = 0xFF000000u | lerp_rgb(top, bottom, y * 256 / GFX_H);
        uint32_t *d = g_px + y * GFX_STRIDE;
        for (x = 0; x < GFX_W; x++) d[x] = c;
    }
}

static void add_edge(float x0, float y0, float x1, float y1) {
    float dir = 1.0f, dxdy, x;
    int y, ys, ye;
    if (y0 == y1) return;
    if (y0 > y1) {
        float t = x0;
        x0 = x1;
        x1 = t;
        t = y0;
        y0 = y1;
        y1 = t;
        dir = -1.0f;
    }
    if (y1 <= 0.0f || y0 >= (float)GFX_H) return;
    dxdy = (x1 - x0) / (y1 - y0);
    x = x0;
    if (y0 < 0.0f) x -= y0 * dxdy;
    ys = y0 < 0.0f ? 0 : (int)y0;
    ye = y1 >= (float)GFX_H ? GFX_H : (int)ceilf(y1);
    if (ys < g_y0) g_y0 = ys;
    if (ye - 1 > g_y1) g_y1 = ye - 1;
    for (y = ys; y < ye; y++) {
        float *line = g_acc + y * ROW;
        float top = (float)y > y0 ? (float)y : y0;
        float bot = (float)(y + 1) < y1 ? (float)(y + 1) : y1;
        float dy = bot - top;
        float xnext = x + dxdy * dy;
        float d = dy * dir;
        float xa = x < xnext ? x : xnext, xb = x < xnext ? xnext : x;
        int x0i, x1i;
        float x0floor, x1ceil;
        if (xa < 0.0f) xa = 0.0f;
        if (xb < 0.0f) xb = 0.0f;
        if (xa > (float)GFX_W) xa = (float)GFX_W;
        if (xb > (float)GFX_W) xb = (float)GFX_W;
        x0floor = floorf(xa);
        x0i = (int)x0floor;
        x1ceil = ceilf(xb);
        x1i = (int)x1ceil;
        if (x0i < g_row_x0[y]) g_row_x0[y] = (short)x0i;
        if (x1i + 1 > g_row_x1[y]) g_row_x1[y] = (short)(x1i + 1);
        if (x1i <= x0i + 1) {
            float xmf = 0.5f * (xa + xb) - x0floor;
            line[x0i] += d - d * xmf;
            line[x0i + 1] += d * xmf;
        } else {
            float s = 1.0f / (xb - xa);
            float x0f = xa - x0floor;
            float a0 = 0.5f * s * (1.0f - x0f) * (1.0f - x0f);
            float x1f = xb - x1ceil + 1.0f;
            float am = 0.5f * s * x1f * x1f;
            line[x0i] += d * a0;
            if (x1i == x0i + 2) {
                line[x0i + 1] += d * (1.0f - a0 - am);
            } else {
                float a1 = s * (1.5f - x0f);
                float a2;
                int xi;
                line[x0i + 1] += d * (a1 - a0);
                for (xi = x0i + 2; xi < x1i - 1; xi++) line[xi] += d * s;
                a2 = a1 + (float)(x1i - x0i - 3) * s;
                line[x1i - 1] += d * (1.0f - a2 - am);
            }
            line[x1i] += d * am;
        }
        x = xnext;
    }
}

void gfx_path_add(const vec2_t *p, int n) {
    int i;
    for (i = 0; i < n; i++) {
        const vec2_t *a = &p[i], *b = &p[(i + 1) % n];
        add_edge(a->x, a->y, b->x, b->y);
    }
}

static inline void blend_px(uint32_t *d, uint32_t rgb, int a256) {
    uint32_t dst = *d;
    *d = 0xFF000000u | lerp_rgb(dst, rgb, a256);
}

/* Interior cells hold exactly 0 in g_acc, so coverage only needs recomputing at shape edges:
 * the long runs between them are a plain store (opaque) or one integer blend (translucent). */
static void fill_rows(uint32_t top, uint32_t bottom, float gy0, float gy1, int use_grad) {
    int y, ymax = g_y1 < GFX_H ? g_y1 : GFX_H - 1;
    float a256 = (float)((int)(top >> 24) * 256 / 255);
    float span = gy1 - gy0;
    for (y = g_y0 < 0 ? 0 : g_y0; y <= ymax; y++) {
        float acc = 0.0f, *a = g_acc + y * ROW;
        uint32_t *d = g_px + y * GFX_STRIDE;
        uint32_t rgb = top & 0xFFFFFFu, solid, pre_rb = 0, pre_g = 0;
        int x = g_row_x0[y], end = g_row_x1[y] + 1, ia = 0, inv = 256;
        g_row_x0[y] = ROW;
        g_row_x1[y] = -1;
        if (end > ROW) end = ROW;
        if (use_grad) {
            float t = span > 0.0f ? ((float)y - gy0) / span : 0.0f;
            int t256 = t <= 0.0f ? 0 : t >= 1.0f ? 256 : (int)(t * 256.0f);
            rgb = lerp_rgb(top, bottom, t256);
        }
        solid = 0xFF000000u | rgb;
        for (; x < end; x++) {
            float v = a[x];
            if (v != 0.0f) {
                float cov;
                a[x] = 0.0f;
                acc += v;
                cov = acc < 0.0f ? -acc : acc;
                if (cov > 1.0f) cov = 1.0f;
                ia = (int)(cov * a256);
                inv = 256 - ia;
                pre_rb = (rgb & 0xFF00FFu) * (uint32_t)ia;
                pre_g = (rgb & 0x00FF00u) * (uint32_t)ia;
            }
            if (x >= GFX_W || ia <= 0) continue;
            if (ia >= 256) {
                d[x] = solid;
            } else {
                uint32_t dst = d[x];
                d[x] = 0xFF000000u | (((pre_rb + (dst & 0xFF00FFu) * (uint32_t)inv) >> 8) & 0xFF00FFu) |
                       (((pre_g + (dst & 0x00FF00u) * (uint32_t)inv) >> 8) & 0x00FF00u);
            }
        }
    }
    g_y0 = GFX_H;
    g_y1 = -1;
}

void gfx_path_fill(uint32_t color) { fill_rows(color, color, 0, 0, 0); }

void gfx_path_fill_vgrad(uint32_t top, uint32_t bottom, float y0, float y1) { fill_rows(top, bottom, y0, y1, 1); }

void gfx_ellipse(float cx, float cy, float rx, float ry, uint32_t color) {
    enum { N = 32 };
    static vec2_t p[N];
    int i;
    if (rx <= 0.0f || ry <= 0.0f) return;
    for (i = 0; i < N; i++) {
        float t = (float)i * 6.2831853f / (float)N;
        p[i].x = cx + rx * cosf(t);
        p[i].y = cy + ry * sinf(t);
    }
    gfx_path_add(p, N);
    gfx_path_fill(color);
}

void gfx_capsule_add(float x0, float y0, float x1, float y1, float r) {
    enum { N = 7 };
    vec2_t p[2 * N];
    float a = atan2f(y1 - y0, x1 - x0);
    int i;
    for (i = 0; i < N; i++) {
        float t = a - 1.5707963f + (float)i * 3.1415927f / (float)(N - 1);
        p[i].x = x1 + r * cosf(t);
        p[i].y = y1 + r * sinf(t);
        t = a + 1.5707963f + (float)i * 3.1415927f / (float)(N - 1);
        p[N + i].x = x0 + r * cosf(t);
        p[N + i].y = y0 + r * sinf(t);
    }
    gfx_path_add(p, 2 * N);
}

void gfx_stroke(const vec2_t *p, int n, float width, uint32_t color) {
    int i;
    for (i = 0; i + 1 < n; i++) gfx_capsule_add(p[i].x, p[i].y, p[i + 1].x, p[i + 1].y, width * 0.5f);
    gfx_path_fill(color);
}

void gfx_rrect(float x, float y, float w, float h, float r, uint32_t color) {
    enum { C = 6 };
    vec2_t p[4 * C];
    static const float sx[4] = {1, -1, -1, 1}, sy[4] = {1, 1, -1, -1};
    int q, i, n = 0;
    float cxs[4], cys[4];
    if (r > w * 0.5f) r = w * 0.5f;
    if (r > h * 0.5f) r = h * 0.5f;
    cxs[0] = x + w - r; cys[0] = y + h - r;
    cxs[1] = x + r;     cys[1] = y + h - r;
    cxs[2] = x + r;     cys[2] = y + r;
    cxs[3] = x + w - r; cys[3] = y + r;
    for (q = 0; q < 4; q++) {
        for (i = 0; i < C; i++) {
            float t = (float)i * 1.5707963f / (float)(C - 1);
            float c = cosf(t), s = sinf(t);
            float dx = (q & 1) ? s : c, dy = (q & 1) ? c : s;
            p[n].x = cxs[q] + sx[q] * dx * r;
            p[n].y = cys[q] + sy[q] * dy * r;
            n++;
        }
    }
    gfx_path_add(p, n);
    gfx_path_fill(color);
}

void gfx_ring(float cx, float cy, float r, float width, float a0, float a1, uint32_t color) {
    enum { MAXN = 40 };
    vec2_t p[MAXN];
    int i, n = (int)(fabsf(a1 - a0) * 6.0f) + 2;
    if (n > MAXN) n = MAXN;
    for (i = 0; i < n; i++) {
        float t = a0 + (a1 - a0) * (float)i / (float)(n - 1);
        p[i].x = cx + r * cosf(t);
        p[i].y = cy + r * sinf(t);
    }
    gfx_stroke(p, n, width, color);
}

/* ---- text ------------------------------------------------------------ */
static const font_glyph_t *glyph(const font_t *f, char c) {
    unsigned char u = (unsigned char)c;
    if (u < 32 || u > 126) u = '?';
    return &f->glyphs[u - 32];
}

int gfx_text_width(const font_t *f, const char *s) {
    int w = 0;
    while (*s) w += glyph(f, *s++)->adv;
    return w;
}

void gfx_text(const font_t *f, int x, int y, const char *s, uint32_t color) {
    uint32_t rgb = color & 0xFFFFFFu;
    int alpha = (int)(color >> 24);
    for (; *s; s++) {
        const font_glyph_t *g = glyph(f, *s);
        const unsigned char *src = f->data + g->off;
        int gx = x + g->xo, gy = y + g->yo, i, j;
        for (j = 0; j < g->h; j++) {
            int py = gy + j;
            if (py >= 0 && py < GFX_H) {
                uint32_t *d = g_px + py * GFX_STRIDE;
                for (i = 0; i < g->w; i++) {
                    int px = gx + i;
                    int a = src[j * g->w + i];
                    if (a && px >= 0 && px < GFX_W) blend_px(&d[px], rgb, (a * alpha + 128) * 256 / 65025);
                }
            }
        }
        x += g->adv;
    }
}

void gfx_text_center(const font_t *f, int cx, int y, const char *s, uint32_t color) {
    gfx_text(f, cx - gfx_text_width(f, s) / 2, y, s, color);
}

void gfx_fit_text(const font_t *f, const char *s, int max_w, char *out, int cap) {
    int w = 0, n = 0, dots = gfx_text_width(f, "..."), keep = 0, keep_w = 0;
    if (cap <= 0) return;
    while (s[n] && n < cap - 1) {
        int a = glyph(f, s[n])->adv;
        if (w + a <= max_w - dots) {
            keep = n + 1;
            keep_w = w + a;
        }
        w += a;
        n++;
    }
    if (!s[n] && w <= max_w) {
        memcpy(out, s, (size_t)n);
        out[n] = 0;
        return;
    }
    (void)keep_w;
    if (keep > cap - 4) keep = cap - 4;
    if (keep < 0) keep = 0;
    memcpy(out, s, (size_t)keep);
    memcpy(out + keep, "...", 4);
}
