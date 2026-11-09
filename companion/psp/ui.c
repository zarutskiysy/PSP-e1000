#include "ui.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "gfx.h"

#define INK GFX_RGB(236, 234, 228)
#define NIGHT GFX_RGB(11, 11, 13)
#define STATUS_Y 232

static uint32_t alpha(uint32_t c, int a) { return (c & 0xFFFFFFu) | ((uint32_t)a << 24); }

void ui_init(ui_view_t *v) {
    memset(v, 0, sizeof *v);
    v->pet_x = 240.0f;
    v->pet_y = 108.0f;
    v->pet_s = 1.0f;
}

void ui_update(ui_view_t *v, const app_t *a, float dt) {
    float k = 1.0f - expf(-dt * 13.0f);
    float tx = 240.0f, ty = 108.0f, ts = 1.0f;
    if (a->ap.phase != AP_NONE) {
        ty = 60.0f;
        ts = .62f;
    } else if (a->menu_open) {
        tx = 128.0f;
        ty = 104.0f;
        ts = .5f;
    } else if (a->diag) {
        tx = 360.0f;
        ts = .45f;
    }
    v->pet_x += (tx - v->pet_x) * k;
    v->pet_y += (ty - v->pet_y) * k;
    v->pet_s += (ts - v->pet_s) * k;
    v->menu_k += ((a->menu_open ? 1.0f : 0.0f) - v->menu_k) * k;
}

static void cross_glyph(float x, float y, uint32_t c) {
    gfx_capsule_add(x - 6, y - 6, x + 6, y + 6, 1.8f);
    gfx_capsule_add(x - 6, y + 6, x + 6, y - 6, 1.8f);
    gfx_path_fill(c);
}

static void circle_glyph(float x, float y, uint32_t c) { gfx_ring(x, y, 7.5f, 3.0f, 0.0f, 6.2831853f, c); }

/* The one line of text on the screen. A toast, the selected action or a reason replaces the status. */
static void draw_status(const app_t *a, uint32_t fg, uint32_t now) {
    char fit[100];
    if (app_toast_visible(a, now)) {
        gfx_fit_text(gfx_font_body, a->toast, 440, fit, sizeof fit);
        gfx_text_center(gfx_font_body, 240, STATUS_Y, fit, fg);
    } else if (a->menu_open && !a->actions[a->selected].enabled) {
        gfx_fit_text(gfx_font_body, a->actions[a->selected].reason, 440, fit, sizeof fit);
        gfx_text_center(gfx_font_body, 240, STATUS_Y, fit, alpha(fg, 170));
    } else if (app_chip_visible(a, now) && !a->menu_open) {
        int enabled = a->actions[a->selected].enabled;
        const char *label = app_action_label(a->selected);
        int w = gfx_text_width(gfx_font_body, label);
        gfx_text(gfx_font_body, 240 - w / 2 + 10, STATUS_Y, label, enabled ? fg : alpha(fg, 110));
        if (enabled) cross_glyph((float)(240 - w / 2 - 12), (float)(STATUS_Y + 9), fg);
    } else {
        gfx_fit_text(gfx_font_body, app_status_text(a), 440, fit, sizeof fit);
        gfx_text_center(gfx_font_body, 240, STATUS_Y, fit, alpha(fg, 225));
    }
}

static void draw_corners(const app_t *a, uint32_t fg) {
    if (!a->link_up) return;
    if (a->mode == PC_MODE_DEMO) gfx_text(gfx_font_small, 12, 8, a->ap.phase != AP_NONE ? "demo - not real" : "demo", alpha(fg, 150));
    if (a->sess_count > 1) {
        char buf[48], fit[40];
        snprintf(buf, sizeof buf, "%s  %d/%d", a->label, a->sess_index + 1, a->sess_count);
        gfx_fit_text(gfx_font_small, buf, 200, fit, sizeof fit);
        gfx_text(gfx_font_small, 468 - gfx_text_width(gfx_font_small, fit), 8, fit, alpha(fg, 130));
    }
}

static void draw_menu(const ui_view_t *v, const app_t *a, uint32_t fg, uint32_t bg) {
    int x = (int)(480.0f - v->menu_k * 224.0f), i;
    if (v->menu_k < .01f) return;
    for (i = 0; i < PC_ACT_COUNT; i++) {
        int y = 40 + i * 26, sel = i == a->selected, en = a->actions[i].enabled;
        uint32_t tc = en ? fg : alpha(fg, 95);
        if (sel) {
            gfx_rrect((float)(x - 10), (float)(y - 3), 212, 24, 3, en ? fg : alpha(fg, 46));
            tc = en ? bg : alpha(fg, 170);
        }
        gfx_text(gfx_font_body, x, y, app_action_label(i), tc);
    }
}

/* Wraps detail into at most two lines; the second is cut with "..." if needed. */
static void wrap2(const char *s, int max_w, char *l1, char *l2, int cap) {
    int n = (int)strlen(s), cut = n, w = 0, i, last_space = -1;
    for (i = 0; i < n; i++) {
        char one[2] = {s[i], 0};
        w += gfx_text_width(gfx_font_body, one);
        if (s[i] == ' ') last_space = i;
        if (w > max_w) {
            cut = last_space > 8 ? last_space : i;
            break;
        }
    }
    if (cut > cap - 1) cut = cap - 1;
    memcpy(l1, s, (size_t)cut);
    l1[cut] = 0;
    l2[0] = 0;
    if (cut < n) gfx_fit_text(gfx_font_body, s + cut + (s[cut] == ' ' ? 1 : 0), max_w, l2, cap);
}

static void draw_approval(const app_t *a, uint32_t fg, uint32_t now) {
    const app_approval_t *ap = &a->ap;
    char l1[100], l2[100], t[40];
    gfx_text_center(gfx_font_title, 240, 122, ap->title[0] ? ap->title : "Approve?", fg);
    wrap2(ap->detail, 420, l1, l2, sizeof l1);
    gfx_text_center(gfx_font_body, 240, 150, l1, alpha(fg, 190));
    if (l2[0]) gfx_text_center(gfx_font_body, 240, 168, l2, alpha(fg, 190));
    if (ap->pending > 1) {
        snprintf(t, sizeof t, "+%d", ap->pending - 1);
        gfx_text(gfx_font_small, 468 - gfx_text_width(gfx_font_small, t), 8, t, alpha(fg, 150));
    } else if (a->mode != PC_MODE_DEMO && a->label[0]) {
        gfx_text(gfx_font_small, 12, 8, a->label, alpha(fg, 130));
    }
    if (ap->phase != AP_SHOWING) {
        gfx_text_center(gfx_font_body, 240, 197, "Sending...", alpha(fg, 170));
        return;
    }
    if (!(ap->flags & PC_AF_ACTIONABLE)) {
        gfx_text_center(gfx_font_body, 240, 192, "Approve this in Codex Desktop", alpha(fg, 200));
        circle_glyph(212.0f, 225.0f, alpha(fg, 200));
        gfx_text(gfx_font_body, 228, 216, "dismiss", alpha(fg, 200));
        return;
    }
    {
        uint32_t c = ap->armed ? fg : alpha(fg, 95);
        cross_glyph(172.0f, 205.0f, c);
        gfx_text(gfx_font_title, 186, 195, "allow", c);
        circle_glyph(290.0f, 205.0f, c);
        gfx_text(gfx_font_title, 304, 195, "deny", c);
    }
    if (ap->timeout_s) {
        float left = 1.0f - (float)(now - ap->shown_ms) / ((float)ap->timeout_s * 1000.0f);
        if (left > 0.0f) gfx_rrect(0, 268, 480.0f * left, 3, 1, alpha(fg, 140));
    }
}

static void draw_diag(const app_t *a, const ui_stats_t *st, uint32_t fg) {
    char b[120];
    int y = 30;
#define LINE(...) do { snprintf(b, sizeof b, __VA_ARGS__); gfx_text(gfx_font_small, 14, y, b, alpha(fg, 175)); y += 14; } while (0)
    LINE("%.0f fps   frame %.1f ms", (double)st->fps, (double)st->frame_ms);
    LINE("io %s   link %s", st->io_name ? st->io_name : "-", a->link_up ? "up" : "down");
    LINE("rx %lu  tx %lu frames", (unsigned long)st->rx_frames, (unsigned long)st->tx_frames);
    LINE("crc err %lu  junk %lu", (unsigned long)st->crc_errors, (unsigned long)st->junk);
    LINE("msgs %lu  bad %lu  drop %lu", (unsigned long)a->rx_msgs, (unsigned long)a->rx_bad, (unsigned long)a->tx_drop);
    LINE("mode %d  conn %d  caps %d  agent %d", a->mode, a->conn, a->caps, a->agent);
    LINE("session %.24s", a->label);
    LINE("peer boot %08lX", (unsigned long)a->peer_boot_id);
#undef LINE
}

void ui_draw(const ui_view_t *v, const app_t *a, pet_t *pet, const ui_stats_t *st, uint32_t now) {
    /* Needing a person is the one thing that changes the whole screen, and it is a hard cut. */
    int asking = a->ap.phase != AP_NONE;
    uint32_t bg = asking ? INK : NIGHT, fg = asking ? NIGHT : INK;
    gfx_clear_vgrad(bg, bg);
    pet_draw(pet, v->pet_x, v->pet_y, v->pet_s, fg, bg);
    draw_corners(a, fg);
    if (asking) {
        draw_approval(a, fg, now);
    } else {
        draw_menu(v, a, fg, bg);
        draw_status(a, fg, now);
        if (a->diag) draw_diag(a, st, fg);
    }
}
