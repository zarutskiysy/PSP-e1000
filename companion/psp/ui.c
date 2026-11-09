#include "ui.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "gfx.h"

#define C_TEXT GFX_RGBA(240, 240, 244, 255)
#define C_DIM GFX_RGBA(150, 154, 168, 255)
#define C_FAINT GFX_RGBA(104, 108, 122, 255)
#define C_PANEL GFX_RGBA(23, 25, 34, 244)
#define C_CROSS GFX_RGB(112, 164, 255)
#define C_CIRCLE GFX_RGB(255, 112, 120)

void ui_init(ui_view_t *v) {
    memset(v, 0, sizeof *v);
    v->pet_x = 240.0f;
    v->pet_y = 112.0f;
    v->pet_s = 1.0f;
}

void ui_update(ui_view_t *v, const app_t *a, float dt) {
    float k = 1.0f - expf(-dt * 13.0f);
    float tx = 240.0f, ty = 112.0f, ts = 1.0f;
    float menu_t = a->menu_open ? 1.0f : 0.0f, ap_t = a->ap.phase != AP_NONE ? 1.0f : 0.0f;
    if (a->ap.phase != AP_NONE) {
        ty = 72.0f;
        ts = .58f;
    } else if (a->menu_open) {
        tx = 128.0f;
        ts = .86f;
    } else if (a->diag) {
        tx = 356.0f;
        ts = .8f;
    }
    v->pet_x += (tx - v->pet_x) * k;
    v->pet_y += (ty - v->pet_y) * k;
    v->pet_s += (ts - v->pet_s) * k;
    v->menu_k += (menu_t - v->menu_k) * k;
    v->ap_k += (ap_t - v->ap_k) * k;
}

static void button_glyph(int x, int cy, int is_cross, int alpha) {
    uint32_t col = ((is_cross ? C_CROSS : C_CIRCLE) & 0xFFFFFFu) | ((uint32_t)alpha << 24);
    gfx_ellipse((float)x, (float)cy, 10.5f, 10.5f, GFX_RGBA(255, 255, 255, alpha / 7));
    if (is_cross) {
        gfx_capsule_add((float)x - 4.2f, (float)cy - 4.2f, (float)x + 4.2f, (float)cy + 4.2f, 1.3f);
        gfx_capsule_add((float)x - 4.2f, (float)cy + 4.2f, (float)x + 4.2f, (float)cy - 4.2f, 1.3f);
        gfx_path_fill(col);
    } else {
        gfx_ring((float)x, (float)cy, 5.2f, 2.4f, 0.0f, 6.2831853f, col);
    }
}

static const char *mode_name(uint8_t mode) {
    switch (mode) {
    case PC_MODE_OBSERVE: return "DESKTOP - WATCHING";
    case PC_MODE_HOOKS: return "DESKTOP - HOOKS";
    case PC_MODE_MANAGED: return "APP SERVER";
    case PC_MODE_DEMO: return "DEMO";
    default: return "";
    }
}

static void draw_top_bar(const app_t *a, const pet_t *pet, uint32_t now) {
    char buf[48];
    const char *m = mode_name(a->mode);
    (void)now;
    if (a->link_up && m[0]) {
        int w = gfx_text_width(gfx_font_small, m) + 16;
        gfx_rrect(10, 8, (float)w, 18, 9, a->mode == PC_MODE_DEMO ? GFX_RGBA(255, 196, 64, 240) : GFX_RGBA(255, 255, 255, 26));
        gfx_text(gfx_font_small, 18, 10, m, a->mode == PC_MODE_DEMO ? GFX_RGB(32, 24, 8) : C_DIM);
    }
    if (a->link_up && a->label[0]) {
        char fit[32];
        if (a->sess_count > 1) snprintf(buf, sizeof buf, "%s  %d/%d", a->label, a->sess_index + 1, a->sess_count);
        else snprintf(buf, sizeof buf, "%s", a->label);
        gfx_fit_text(gfx_font_small, buf, 200, fit, sizeof fit);
        gfx_text(gfx_font_small, 470 - gfx_text_width(gfx_font_small, fit), 10, fit, C_DIM);
    }
    (void)pet;
}

static void draw_status(const app_t *a, const pet_t *pet, uint32_t now) {
    char fit[100];
    int y = 219;
    gfx_fit_text(gfx_font_body, app_status_text(a), 440, fit, sizeof fit);
    gfx_text_center(gfx_font_body, 240, y, fit, C_TEXT);
    if (app_chip_visible(a, now) && !a->menu_open) {
        char chip[60];
        int enabled = a->actions[a->selected].enabled, w;
        snprintf(chip, sizeof chip, "%s", app_action_label(a->selected));
        w = gfx_text_width(gfx_font_small, chip);
        gfx_rrect((float)(240 - w / 2 - 12), 240, (float)(w + 42), 20, 10, GFX_RGBA(255, 255, 255, 26));
        gfx_text(gfx_font_small, 240 - w / 2, 243, chip, enabled ? C_TEXT : C_FAINT);
        if (enabled) button_glyph(240 + w / 2 + 16, 250, 1, 255);
    } else if (a->link_up) {
        gfx_text_center(gfx_font_small, 240, 247, a->conn == PC_CONN_ATTACHED ? "START  actions      SELECT  info" : "SELECT  info", C_FAINT);
    }
    (void)pet;
}

static void draw_menu(const ui_view_t *v, const app_t *a, const pet_t *pet) {
    float x = 480.0f - v->menu_k * 228.0f;
    float y = 36.0f;
    int i;
    char fit[60];
    if (v->menu_k < .01f) return;
    gfx_rrect(x, y, 218, 170, 12, C_PANEL);
    gfx_text(gfx_font_small, (int)x + 14, (int)y + 9, "QUICK ACTIONS", C_FAINT);
    for (i = 0; i < PC_ACT_COUNT; i++) {
        float ry = y + 28.0f + (float)i * 22.0f;
        int sel = i == a->selected, en = a->actions[i].enabled;
        if (sel) gfx_rrect(x + 8, ry - 2, 202, 22, 7, en ? pet_accent(pet, 52) : GFX_RGBA(255, 255, 255, 18));
        gfx_text(gfx_font_body, (int)x + 16, (int)ry, app_action_label(i), en ? C_TEXT : C_FAINT);
    }
    if (a->actions[a->selected].enabled) {
        button_glyph((int)x + 24, (int)y + 152, 1, 255);
        gfx_text(gfx_font_small, (int)x + 38, (int)y + 146, "run", C_DIM);
        button_glyph((int)x + 84, (int)y + 152, 0, 255);
        gfx_text(gfx_font_small, (int)x + 98, (int)y + 146, "close", C_DIM);
    } else {
        gfx_fit_text(gfx_font_small, a->actions[a->selected].reason, 196, fit, sizeof fit);
        gfx_text(gfx_font_small, (int)x + 12, (int)y + 146, fit, GFX_RGB(255, 186, 110));
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

static void draw_approval(const ui_view_t *v, const app_t *a, const pet_t *pet, uint32_t now) {
    const app_approval_t *ap = &a->ap;
    float y = 272.0f - v->ap_k * 146.0f;
    int iy = (int)y;
    char l1[100], l2[100], t[40];
    if (v->ap_k < .01f || ap->phase == AP_NONE) return;
    gfx_rrect(24, y, 432, 136, 14, C_PANEL);
    gfx_rrect(24, y, 432, 3, 1.5f, pet_accent(pet, 255));
    if (ap->pending > 1) {
        snprintf(t, sizeof t, "+%d more", ap->pending - 1);
        gfx_text(gfx_font_small, 440 - gfx_text_width(gfx_font_small, t), iy + 9, t, C_DIM);
    }
    if (ap->flags & PC_AF_DEMO) gfx_text(gfx_font_small, 36, iy + 9, "DEMO - not real", GFX_RGB(255, 196, 64));
    gfx_text_center(gfx_font_title, 240, iy + 9, ap->title[0] ? ap->title : "Approve?", C_TEXT);
    wrap2(ap->detail, 396, l1, l2, sizeof l1);
    gfx_text_center(gfx_font_body, 240, iy + 37, l1, GFX_RGB(255, 214, 150));
    if (l2[0]) gfx_text_center(gfx_font_body, 240, iy + 55, l2, GFX_RGB(255, 214, 150));

    if (ap->phase == AP_SHOWING) {
        if (ap->flags & PC_AF_ACTIONABLE) {
            int left = 0;
            if (ap->timeout_s) {
                int el = (int)((now - ap->shown_ms) / 1000u);
                left = (int)ap->timeout_s - el;
                if (left < 0) left = 0;
                snprintf(t, sizeof t, "%d s", left);
                gfx_text_center(gfx_font_small, 240, iy + 86, t, C_FAINT);
            }
            {
                int alpha = ap->armed ? 255 : 110;
                uint32_t tc = ap->armed ? C_TEXT : C_FAINT;
                button_glyph(120, iy + 109, 1, alpha);
                gfx_text(gfx_font_title, 138, iy + 99, "ALLOW", tc);
                button_glyph(300, iy + 109, 0, alpha);
                gfx_text(gfx_font_title, 318, iy + 99, "DENY", tc);
            }
        } else {
            gfx_text_center(gfx_font_body, 240, iy + 80, "Approve this in Codex Desktop", C_DIM);
            button_glyph(208, iy + 111, 0, 255);
            gfx_text(gfx_font_small, 226, iy + 104, "dismiss", C_DIM);
        }
    } else {
        gfx_text_center(gfx_font_body, 240, iy + 99, ap->decision == PC_DECISION_ALLOW ? "Sending ALLOW to Codex..." : "Sending DENY to Codex...", C_DIM);
    }
}

static void draw_toast(const app_t *a, uint32_t now) {
    char fit[80];
    int w;
    uint32_t bg;
    if (!app_toast_visible(a, now)) return;
    gfx_fit_text(gfx_font_body, a->toast, 380, fit, sizeof fit);
    w = gfx_text_width(gfx_font_body, fit);
    bg = a->toast_kind == TOAST_OK ? GFX_RGBA(44, 148, 96, 244) : a->toast_kind == TOAST_ERR ? GFX_RGBA(176, 56, 64, 244) : GFX_RGBA(56, 62, 84, 244);
    gfx_rrect((float)(240 - w / 2 - 14), 5, (float)(w + 28), 26, 13, bg);
    gfx_text_center(gfx_font_body, 240, 9, fit, GFX_RGB(255, 255, 255));
}

static void draw_diag(const app_t *a, const ui_stats_t *st) {
    char b[120];
    int y = 34;
    gfx_rrect(8, 30, 238, 118, 9, GFX_RGBA(12, 13, 18, 228));
#define LINE(...) do { snprintf(b, sizeof b, __VA_ARGS__); gfx_text(gfx_font_small, 16, y, b, C_DIM); y += 14; } while (0)
    LINE("%.0f fps   frame %.1f ms   q%d", (double)st->fps, (double)st->frame_ms, st->quality);
    LINE("io %s   link %s", st->io_name ? st->io_name : "-", a->link_up ? "up" : "down");
    LINE("rx %lu  tx %lu frames", (unsigned long)st->rx_frames, (unsigned long)st->tx_frames);
    LINE("crc err %lu  junk %lu", (unsigned long)st->crc_errors, (unsigned long)st->junk);
    LINE("msgs %lu  bad %lu  drop %lu", (unsigned long)a->rx_msgs, (unsigned long)a->rx_bad, (unsigned long)a->tx_drop);
    LINE("mode %d  conn %d  caps %d  agent %d", a->mode, a->conn, a->caps, a->agent);
    LINE("peer boot %08lX", (unsigned long)a->peer_boot_id);
    LINE("%.40s", a->note);
#undef LINE
}

void ui_draw(const ui_view_t *v, const app_t *a, pet_t *pet, const ui_stats_t *st, uint32_t now) {
    gfx_clear_vgrad(GFX_RGB(15, 16, 24), GFX_RGB(8, 9, 13));
    pet_draw(pet, v->pet_x, v->pet_y, v->pet_s);
    draw_top_bar(a, pet, now);
    if (a->ap.phase == AP_NONE && v->ap_k < .5f) draw_status(a, pet, now);
    draw_menu(v, a, pet);
    draw_approval(v, a, pet, now);
    draw_toast(a, now);
    if (a->diag) draw_diag(a, st);
}
