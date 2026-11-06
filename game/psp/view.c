/* view.c — draws the console state: sonar scope (left 272x272) + text console (right 208 px). */
#include "view.h"
#include <math.h>
#include <string.h>

#define SC_X 136
#define SC_Y 136
#define SC_R 128
#define PANEL_X 280

#define C_BG BW_RGB(0, 8, 10)
#define C_GRID BW_RGB(0, 70, 60)
#define C_SCOPE BW_RGB(0, 200, 160)
#define C_TEXT BW_RGB(150, 230, 200)
#define C_DIM BW_RGB(60, 120, 100)
#define C_WARN BW_RGB(255, 80, 60)
#define C_MINE BW_RGB(255, 210, 60)
#define C_CREATURE BW_RGB(255, 60, 60)
#define C_GATE BW_RGB(80, 160, 255)
#define C_EXIT BW_RGB(80, 255, 120)
#define C_SUB BW_RGB(255, 255, 255)

static char *put_uint(char *p, unsigned v) {
    char tmp[12];
    int n = 0;
    do { tmp[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) *p++ = tmp[--n];
    *p = 0;
    return p;
}
static char *put_str(char *p, const char *s) {
    while (*s) *p++ = *s++;
    *p = 0;
    return p;
}

static void bar(bw_gfx_t *g, int x, int y, const char *label, int v, int max, uint32_t c) {
    int w = 120, f = max ? v * w / max : 0;
    char num[8];
    bw_text(g, x, y, label, C_DIM, 1);
    bw_rect(g, x + 42, y - 1, w + 2, 9, C_GRID);
    bw_fill_rect(g, x + 43, y, f, 7, c);
    put_uint(num, (unsigned)v);
    bw_text(g, x + 42 + w + 6, y, num, C_TEXT, 1);
}

static uint32_t kind_color(int kind) {
    switch (kind) {
    case BW_K_MINE: return C_MINE;
    case BW_K_CREATURE: return C_CREATURE;
    case BW_K_GATE: return C_GATE;
    case BW_K_EXIT: return C_EXIT;
    default: return C_DIM;
    }
}

static void draw_scope(bw_gfx_t *g, const bw_console_t *c) {
    uint32_t t = c->now_ms;
    float scale = (float)SC_R / (float)(c->game.max_range ? c->game.max_range : 700);
    int i;
    bw_circle(g, SC_X, SC_Y, SC_R, C_SCOPE);
    bw_circle(g, SC_X, SC_Y, SC_R * 2 / 3, C_GRID);
    bw_circle(g, SC_X, SC_Y, SC_R / 3, C_GRID);
    bw_line(g, SC_X - SC_R, SC_Y, SC_X + SC_R, SC_Y, C_GRID);
    bw_line(g, SC_X, SC_Y - SC_R, SC_X, SC_Y + SC_R, C_GRID);
    bw_text(g, SC_X - 2, SC_Y - SC_R + 3, "N", C_DIM, 1);
    /* cosmetic sweep: one turn per 3 s with a short fading tail */
    for (i = 0; i < 6; i++) {
        float a = (float)((t + 3000u - (uint32_t)i * 40u) % 3000u) * (6.2831853f / 3000.0f);
        bw_line(g, SC_X, SC_Y, SC_X + (int)(sinf(a) * SC_R), SC_Y - (int)(cosf(a) * SC_R),
                bw_scale_color(C_SCOPE, 6 - i, 8));
    }
    /* active ping ring (expands for 700 ms) */
    if (c->pings_sent && t - c->last_ping_ms < 700u) {
        int r = (int)((t - c->last_ping_ms) * SC_R / 700u);
        bw_circle(g, SC_X, SC_Y, r, C_SUB);
        bw_circle(g, SC_X, SC_Y, r + 1, C_SCOPE);
    }
    /* contacts */
    for (i = 0; i < c->ncontacts; i++) {
        const bw_contact_t *k = &c->contacts[i];
        uint32_t age = t - k->t_ms, life = k->passive ? 3000u : 8000u;
        uint32_t col;
        int x, y;
        if (age >= life) continue;
        col = bw_scale_color(kind_color(k->kind), (int)(life - age), (int)life);
        if (k->passive) {
            float dx, dy;
            int j;
            bw_bearing_vec(k->bearing, &dx, &dy);
            for (j = 10; j < SC_R; j += 6)
                bw_line(g, SC_X + (int)(dx * j), SC_Y + (int)(dy * j), SC_X + (int)(dx * (j + 3)),
                        SC_Y + (int)(dy * (j + 3)), col);
            continue;
        }
        x = SC_X + (int)((k->wx - (float)c->sub.x) * scale);
        y = SC_Y + (int)((k->wy - (float)c->sub.y) * scale);
        if ((x - SC_X) * (x - SC_X) + (y - SC_Y) * (y - SC_Y) > SC_R * SC_R) continue;
        switch (k->kind) {
        case BW_K_MINE:
            bw_line(g, x - 3, y - 3, x + 3, y + 3, col);
            bw_line(g, x - 3, y + 3, x + 3, y - 3, col);
            break;
        case BW_K_CREATURE:
            bw_fill_circle(g, x, y, 4 + (int)((t / 150u) % 2u), col);
            break;
        case BW_K_GATE: bw_fill_rect(g, x - 7, y - 1, 15, 3, col); break;
        case BW_K_EXIT: bw_rect(g, x - 4, y - 4, 9, 9, col); bw_pixel(g, x, y, col); break;
        default: bw_pixel(g, x, y, col); break;
        }
        if (k->marked) bw_circle(g, x, y, 7, C_SUB);
    }
    /* own sub: triangle pointing along heading */
    {
        float dx, dy;
        bw_bearing_vec(c->sub.heading, &dx, &dy);
        bw_line(g, SC_X + (int)(dx * 8), SC_Y + (int)(dy * 8), SC_X - (int)(dx * 4 - dy * 4),
                SC_Y - (int)(dy * 4 + dx * 4), C_SUB);
        bw_line(g, SC_X + (int)(dx * 8), SC_Y + (int)(dy * 8), SC_X - (int)(dx * 4 + dy * 4),
                SC_Y - (int)(dy * 4 - dx * 4), C_SUB);
        bw_line(g, SC_X - (int)(dx * 4 - dy * 4), SC_Y - (int)(dy * 4 + dx * 4), SC_X - (int)(dx * 4 + dy * 4),
                SC_Y - (int)(dy * 4 - dx * 4), C_SUB);
    }
}

static void draw_hack(bw_gfx_t *g, const bw_console_t *c, int y) {
    char line[40], *p;
    int i, bw = 22, gap = 8, x0 = PANEL_X + 4;
    uint32_t left = (int32_t)(c->hack_deadline_ms - c->now_ms) > 0 ? c->hack_deadline_ms - c->now_ms : 0;
    uint32_t total = c->hack_deadline_ms > c->hack_start_ms ? c->hack_deadline_ms - c->hack_start_ms : 1;
    p = put_str(line, "GATE ");
    p = put_uint(p, c->hack_gate);
    put_str(p, " PHASE LOCK");
    bw_text(g, x0, y, line, C_GATE, 1);
    p = put_uint(line, left / 1000u);
    p = put_str(p, ".");
    p = put_uint(p, (left / 100u) % 10u);
    put_str(p, "S");
    bw_text(g, x0 + 150, y, line, left < 3000u ? C_WARN : C_TEXT, 1);
    bw_fill_rect(g, x0, y + 10, (int)(196u * (left > total ? total : left) / total), 3, left < 3000u ? C_WARN : C_GATE);
    /* target wave (top) and the player's wave (bottom) */
    bw_text(g, x0, y + 18, "TARGET", C_DIM, 1);
    bw_text(g, x0, y + 70, "YOURS", C_DIM, 1);
    for (i = 0; i < c->hack_n; i++) {
        int x = x0 + 4 + i * (bw + gap), ht = 4 + c->hack_target[i] * 5, hv = 4 + c->hack_val[i] * 5;
        int match = c->hack_target[i] == c->hack_val[i];
        bw_fill_rect(g, x, y + 66 - ht, bw, ht, C_GATE);
        bw_fill_rect(g, x, y + 118 - hv, bw, hv, match ? C_EXIT : C_MINE);
        if (i == c->hack_cursor) bw_rect(g, x - 3, y + 78, bw + 6, 44, C_SUB);
        if (i > 0) { /* connect the tops like a waveform */
            int px = x0 + 4 + (i - 1) * (bw + gap) + bw;
            bw_line(g, px, y + 66 - (4 + c->hack_target[i - 1] * 5), x, y + 66 - ht, C_GRID);
        }
    }
    bw_text(g, x0, y + 128, "D-PAD TUNE  X LOCK  O ABORT", C_DIM, 1);
}

void bw_view_draw(bw_gfx_t *g, const bw_console_t *c, const char *io_name) {
    char line[48], *p;
    int i, y;
    int alert = (int32_t)(c->alert_until_ms - c->now_ms) > 0;
    bw_clear(g, C_BG);
    if (alert && (c->now_ms / 120u) % 2u) bw_rect(g, 0, 0, BW_SCREEN_W, BW_SCREEN_H, C_WARN);
    draw_scope(g, c);
    bw_line(g, PANEL_X - 6, 4, PANEL_X - 6, BW_SCREEN_H - 5, C_GRID);

    bw_text(g, PANEL_X, 4, "BLACKWATER PING", C_SCOPE, 1);
    p = put_str(line, c->link_up ? "LINK " : "NO LINK ");
    put_str(p, io_name ? io_name : "");
    bw_text(g, PANEL_X + 100, 4, line, c->link_up ? C_EXIT : C_WARN, 1);

    if (c->phase == BW_PH_TITLE) {
        bw_text(g, PANEL_X, 26, "SONAR + LOCK CONSOLE", C_TEXT, 1);
        bw_text(g, PANEL_X, 44, "X   ACTIVE PING", C_TEXT, 1);
        bw_text(g, PANEL_X, 54, "    (LOUD! IT HEARS)", C_DIM, 1);
        bw_text(g, PANEL_X, 66, "SQ  PASSIVE LISTEN", C_TEXT, 1);
        bw_text(g, PANEL_X, 78, "TRI MARK NEAREST THREAT", C_TEXT, 1);
        bw_text(g, PANEL_X, 90, "NUB STEER (SOLO MODE)", C_TEXT, 1);
        bw_text(g, PANEL_X, 112, (c->now_ms / 500u) % 2u ? "PRESS START" : "", C_SUB, 2);
        y = 150;
    } else {
        y = 20;
        bar(g, PANEL_X, y, "HULL", c->sub.hull, 100, c->sub.hull < 35 ? C_WARN : C_EXIT);
        bar(g, PANEL_X, y + 11, "BATT", c->sub.battery, 100, c->sub.battery < 20 ? C_WARN : C_MINE);
        bar(g, PANEL_X, y + 22, "NOISE", c->sub.noise, 100, C_CREATURE);
        p = put_str(line, "DEPTH ");
        p = put_uint(p, (unsigned)(c->sub.y > 0 ? c->sub.y : 0));
        p = put_str(p, "  GATES ");
        put_uint(p, c->sub.gates_open);
        bw_text(g, PANEL_X, y + 35, line, C_TEXT, 1);
        if (c->phase == BW_PH_HACK) {
            draw_hack(g, c, 70);
            y = 215;
        } else if (c->phase == BW_PH_OVER) {
            bw_text(g, PANEL_X, 74, c->outcome == 1 ? "SURFACED" : "LOST", c->outcome == 1 ? C_EXIT : C_WARN, 3);
            bw_text(g, PANEL_X, 104, "START: DIVE AGAIN", C_TEXT, 1);
            y = 130;
        } else {
            uint32_t cd = c->pings_sent && c->now_ms - c->last_ping_ms < BW_PING_COOLDOWN_MS
                              ? BW_PING_COOLDOWN_MS - (c->now_ms - c->last_ping_ms) : 0;
            bw_text(g, PANEL_X, 70, cd ? "PING CHARGING" : "PING READY  (X)", cd ? C_DIM : C_SUB, 1);
            bw_text(g, PANEL_X, 82, "SQ LISTEN  TRI MARK", C_DIM, 1);
            p = put_str(line, "PINGS ");
            p = put_uint(p, (unsigned)c->pings_sent);
            p = put_str(p, " ECHOES ");
            put_uint(p, (unsigned)c->echoes_rx);
            bw_text(g, PANEL_X, 94, line, C_DIM, 1);
            y = 130;
        }
    }
    /* log */
    for (i = 0; i < BW_LOG_LINES && y + i * 9 < BW_SCREEN_H - 8; i++)
        bw_text(g, PANEL_X, y + i * 9, c->log[i], i == BW_LOG_LINES - 1 ? C_TEXT : C_DIM, 1);
}
