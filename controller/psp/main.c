/* PSP control deck: streams pad/nub state to the Mac (INPUT_STATE, every vblank) and shows a
 * radial action wheel (hold SELECT, aim with the nub, release to fire). Labels come from the Mac
 * (WHEEL_CONFIG); the Mac runs the macro and answers with ACTION_RESULT.
 * Transport is chosen once in deck_io.c; this file only sees psp_link_t. */
#include <math.h>
#include <pspctrl.h>
#include <pspdebug.h>
#include <pspdisplay.h>
#include <pspkernel.h>
#include <stdio.h>
#include <string.h>

#include "../../common/psp/link.h"
#include "../proto_controller.h"
#include "deck_io.h"

PSP_MODULE_INFO("PSPDECK", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);
PSP_HEAP_SIZE_KB(-1024);

#define SCR_W 480
#define SCR_H 272
#define STRIDE 512
#define VRAM ((u32 *)0x44000000) /* uncached VRAM, display buffer 0 */

/* colours are 0xAABBGGRR (PSP 8888) */
#define C_BG 0xFF201814u
#define C_PANEL 0xFF302820u
#define C_TEXT 0xFFFFFFFFu
#define C_DIM 0xFF908070u
#define C_OK 0xFF60E060u
#define C_ERR 0xFF5050F0u
#define C_ACCENT 0xFF20A0F0u
#define C_SLICE_A 0xFF584030u
#define C_SLICE_B 0xFF4C3828u
#define C_SLICE_HOVER 0xFF2090F0u
#define C_BORDER 0xFFC0B0A0u

static u32 bb[STRIDE * SCR_H] __attribute__((aligned(64))); /* back buffer in RAM */

static volatile int running = 1;
static int exit_cb(int a, int b, void *c) {
    (void)a; (void)b; (void)c;
    running = 0;
    return 0;
}
static int cb_thread(SceSize args, void *argp) {
    (void)args; (void)argp;
    int cbid = sceKernelCreateCallback("exit", exit_cb, NULL);
    sceKernelRegisterExitCallback(cbid);
    sceKernelSleepThreadCB();
    return 0;
}

/* ---- drawing ---------------------------------------------------------- */
static void fill(int x, int y, int w, int h, u32 c) {
    int i, j;
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > SCR_W) w = SCR_W - x;
    if (y + h > SCR_H) h = SCR_H - y;
    for (j = 0; j < h; j++) {
        u32 *p = bb + (y + j) * STRIDE + x;
        for (i = 0; i < w; i++) p[i] = c;
    }
}
static void text(int col, int row, u32 color, const char *s) {
    pspDebugScreenSetTextColor(color);
    pspDebugScreenSetXY(col, row);
    pspDebugScreenPuts(s);
}
static void textf_px(int x, int y, u32 color, const char *s) { /* pixel-positioned, via PutChar */
    while (*s) {
        if (x >= 0 && x <= SCR_W - 8 && y >= 0 && y <= SCR_H - 8) pspDebugScreenPutChar(x, y, color, (u8)*s);
        x += 8;
        s++;
    }
}

/* ---- action wheel ------------------------------------------------------ */
#define WCX 352
#define WCY 140
#define WR 112
#define WRIN 30
#define WMAP (2 * WR + 1)
static uint8_t wheel_map[WMAP * WMAP]; /* slice index, 0xFE border, 0xFF outside */
static int wheel_n = 0;
static char labels[CTRL_WHEEL_MAX][CTRL_LABEL_LEN];
static int map_built_for = -1;

static int slice_of_angle(float dx, float dy, int n) { /* 0 at 12 o'clock, clockwise */
    float a = atan2f(dx, -dy);
    float step = 2.0f * (float)M_PI / n;
    int s;
    if (a < 0) a += 2.0f * (float)M_PI;
    s = (int)((a + step / 2) / step);
    return s % n;
}

static void build_wheel_map(int n) {
    int x, y;
    int nn = n > 0 ? n : 6;
    float step = 2.0f * (float)M_PI / nn;
    for (y = 0; y < WMAP; y++)
        for (x = 0; x < WMAP; x++) {
            float dx = (float)(x - WR), dy = (float)(y - WR);
            float d = sqrtf(dx * dx + dy * dy);
            uint8_t v = 0xFF;
            if (d <= WR && d >= WRIN) {
                float a = atan2f(dx, -dy), rel;
                if (a < 0) a += 2.0f * (float)M_PI;
                rel = fmodf(a + step / 2, step); /* distance from a slice boundary, in radians */
                if (rel > step / 2) rel = step - rel;
                if (d > WR - 1.5f || d < WRIN + 1.5f || rel * d < 1.2f)
                    v = 0xFE;
                else
                    v = (uint8_t)slice_of_angle(dx, dy, nn);
            }
            wheel_map[y * WMAP + x] = v;
        }
    map_built_for = n;
}

static void draw_wheel(int open, int hover) {
    int x, y, i;
    int nn = wheel_n > 0 ? wheel_n : 6;
    if (map_built_for != wheel_n) build_wheel_map(wheel_n);
    for (y = 0; y < WMAP; y++) {
        u32 *row = bb + (WCY - WR + y) * STRIDE + (WCX - WR);
        const uint8_t *m = wheel_map + y * WMAP;
        for (x = 0; x < WMAP; x++) {
            uint8_t v = m[x];
            if (v == 0xFF) continue;
            if (v == 0xFE)
                row[x] = open ? C_BORDER : C_DIM;
            else if (open && v == hover)
                row[x] = C_SLICE_HOVER;
            else
                row[x] = (v & 1) ? C_SLICE_B : C_SLICE_A;
        }
    }
    for (i = 0; i < nn; i++) {
        float a = 2.0f * (float)M_PI * i / nn;
        int lx = WCX + (int)(sinf(a) * (WR + WRIN) / 2);
        int ly = WCY - (int)(cosf(a) * (WR + WRIN) / 2);
        const char *s = (i < wheel_n) ? labels[i] : "--";
        char buf[13];
        snprintf(buf, sizeof buf, "%s", s); /* 12 chars max inside a slice */
        textf_px(lx - (int)strlen(buf) * 4, ly - 4, (open && i == hover) ? 0xFF000000u : (open ? C_TEXT : C_DIM), buf);
    }
    textf_px(WCX - 16, WCY - 4, open ? C_ACCENT : C_DIM, open ? "AIM" : "SEL");
}

/* ---- app state --------------------------------------------------------- */
static psp_link_t link;
static uint8_t rx_payload[512], tx_buf[512], rx_chunk[2048];
static deck_io_t dio;
static int have_config;
static char last_msg[CTRL_RESULT_TEXT_LEN + 16] = "";
static u32 last_msg_color = C_DIM;
static unsigned psp_rtt_us, mac_rtt_us, mac_events, mac_input_hz;
static int mac_dry, mac_ax, link_errors, peer_seen;
static unsigned tx_inputs;

#define PING_MAGIC 0x474B5044u /* "DPKG" */

static void handle_frame(const psp_link_frame_t *f) {
    unsigned i;
    switch (f->type) {
    case PSP_LINK_T_HELLO:
    case PSP_LINK_T_HELLO_ACK:
        peer_seen = 1;
        break;
    case CTRL_T_WHEEL_CONFIG:
        if (f->len >= CTRL_WHEEL_CONFIG_SIZE) {
            int n = f->payload[0];
            if (n > (int)CTRL_WHEEL_MAX) n = CTRL_WHEEL_MAX;
            for (i = 0; i < CTRL_WHEEL_MAX; i++) {
                memcpy(labels[i], f->payload + 4 + i * CTRL_LABEL_LEN, CTRL_LABEL_LEN);
                labels[i][CTRL_LABEL_LEN - 1] = 0;
            }
            wheel_n = n;
            have_config = 1;
            peer_seen = 1;
        }
        break;
    case CTRL_T_ACTION_RESULT:
        if (f->len >= CTRL_ACTION_RESULT_SIZE) {
            char t[CTRL_RESULT_TEXT_LEN + 1];
            memcpy(t, f->payload + 4, CTRL_RESULT_TEXT_LEN);
            t[CTRL_RESULT_TEXT_LEN] = 0;
            snprintf(last_msg, sizeof last_msg, "%s %s", f->payload[1] ? "OK " : "ERR", t);
            last_msg_color = f->payload[1] ? C_OK : C_ERR;
        }
        break;
    case CTRL_T_MAC_STATUS:
        if (f->len >= CTRL_MAC_STATUS_SIZE) {
            mac_rtt_us = psp_link_get_u32(f->payload);
            mac_events = psp_link_get_u32(f->payload + 4);
            mac_input_hz = psp_link_get_u16(f->payload + 8);
            mac_dry = f->payload[10];
            mac_ax = f->payload[11];
        }
        break;
    case PSP_LINK_T_PONG:
        if (f->len == 8 && psp_link_get_u32(f->payload) == PING_MAGIC)
            psp_rtt_us = sceKernelGetSystemTimeLow() - psp_link_get_u32(f->payload + 4);
        break;
    default:
        break;
    }
}

static int nub_slice(int lx, int ly, int n) {
    float dx = (float)(lx - 128), dy = (float)(ly - 128);
    if (n <= 0 || dx * dx + dy * dy < 55.0f * 55.0f) return CTRL_NO_SLICE;
    return slice_of_angle(dx, dy, n);
}

static void draw_button(int col, int row, const char *name, int on) {
    pspDebugScreenSetTextColor(on ? 0xFF000000u : C_DIM);
    if (on) fill(col * 8 - 1, row * 8 - 1, (int)strlen(name) * 8 + 2, 10, C_ACCENT);
    pspDebugScreenSetXY(col, row);
    pspDebugScreenPuts(name);
}

int main(void) {
    SceUID th = sceKernelCreateThread("cb", cb_thread, 0x11, 0xFA0, 0, 0);
    SceCtrlData pad;
    unsigned frame = 0, last_hello = 0, last_ping = 0;
    int wheel_open = 0, hover = CTRL_NO_SLICE;
    char line[96];

    if (th >= 0) sceKernelStartThread(th, 0, 0);
    sceCtrlSetSamplingCycle(0);
    sceCtrlSetSamplingMode(PSP_CTRL_MODE_ANALOG);
    sceDisplaySetMode(0, SCR_W, SCR_H);
    sceDisplaySetFrameBuf((void *)VRAM, STRIDE, PSP_DISPLAY_PIXEL_FORMAT_8888, PSP_DISPLAY_SETBUF_NEXTFRAME);
    pspDebugScreenInitEx(bb, PSP_DISPLAY_PIXEL_FORMAT_8888, 0);
    pspDebugScreenEnableBackColor(0);

    sceCtrlPeekBufferPositive(&pad, 1);
    deck_io_open(&dio, (pad.Buttons & PSP_CTRL_TRIANGLE) != 0);
    psp_link_init(&link, dio.io, rx_payload, sizeof rx_payload, tx_buf, sizeof tx_buf, rx_chunk, sizeof rx_chunk);
    link.app = CTRL_APP_ID;
    link.name = "psp_deck";
    build_wheel_map(0);

    while (running) {
        unsigned now;
        psp_link_frame_t f;
        int r, ready;
        sceCtrlPeekBufferPositive(&pad, 1);
        now = sceKernelGetSystemTimeLow();
        deck_io_service(&dio);
        ready = deck_io_ready(&dio);

        /* incoming */
        while ((r = psp_link_poll(&link, 0, &f)) == 1) handle_frame(&f);
        if (r < 0) link_errors++;

        /* wheel state machine: hold SELECT to open, release to fire the hovered slice */
        if (pad.Buttons & PSP_CTRL_SELECT) {
            wheel_open = 1;
            hover = nub_slice(pad.Lx, pad.Ly, wheel_n);
        } else if (wheel_open) {
            wheel_open = 0;
            if (hover != CTRL_NO_SLICE && have_config && ready) {
                uint8_t p[CTRL_WHEEL_FIRE_SIZE] = {0};
                p[0] = (uint8_t)hover;
                psp_link_put_u32(p + 4, now);
                psp_link_send(&link, CTRL_T_WHEEL_FIRE, 0, p, sizeof p);
                snprintf(last_msg, sizeof last_msg, "fired: %s ...", labels[hover]);
                last_msg_color = C_ACCENT;
            } else if (hover != CTRL_NO_SLICE) {
                snprintf(last_msg, sizeof last_msg, "not connected: wheel needs the Mac");
                last_msg_color = C_ERR;
            }
            hover = CTRL_NO_SLICE;
        }

        /* outgoing */
        if (ready) {
            uint8_t p[CTRL_INPUT_SIZE];
            if (!have_config && now - last_hello >= 1000000u) {
                psp_link_send_hello(&link, PSP_LINK_T_HELLO, CTRL_APP_ID, "psp_deck");
                psp_link_send(&link, CTRL_T_CONFIG_REQ, 0, NULL, 0);
                last_hello = now;
            }
            if (now - last_ping >= 1000000u) {
                uint8_t pp[8];
                psp_link_put_u32(pp, PING_MAGIC);
                psp_link_put_u32(pp + 4, now);
                psp_link_send(&link, PSP_LINK_T_PING, 0, pp, sizeof pp);
                last_ping = now;
            }
            psp_link_put_u32(p, pad.Buttons);
            p[4] = pad.Lx;
            p[5] = pad.Ly;
            p[6] = wheel_open ? CTRL_IN_F_WHEEL_OPEN : 0;
            p[7] = (uint8_t)(wheel_open ? hover : CTRL_NO_SLICE);
            psp_link_put_u32(p + 8, now);
            psp_link_put_u32(p + 12, frame);
            if (psp_link_send(&link, CTRL_T_INPUT_STATE, 0, p, sizeof p) == 0) tx_inputs++;
            else link_errors++;
        }

        /* ---- render ---- */
        fill(0, 0, SCR_W, SCR_H, C_BG);
        fill(0, 0, SCR_W, 11, C_PANEL);
        text(0, 0, C_ACCENT, "PSP DECK");
        snprintf(line, sizeof line, "io:%s  %s", dio.name, deck_io_state_text(&dio));
        text(10, 0, C_TEXT, line);
        text(48, 0, have_config ? C_OK : C_ERR, have_config ? "MAC LINKED" : "NO MAC   ");

        snprintf(line, sizeof line, "%.29s", dio.note);
        text(0, 2, C_DIM, line);
        text(0, 3, C_DIM, dio.emulator ? "running in emulator" : "running on PSP");
        snprintf(line, sizeof line, "rtt psp->mac->psp %u.%u ms", psp_rtt_us / 1000, (psp_rtt_us / 100) % 10);
        text(0, 5, C_TEXT, line);
        snprintf(line, sizeof line, "mac rtt %u.%u ms  in %u Hz", mac_rtt_us / 1000, (mac_rtt_us / 100) % 10,
                 mac_input_hz);
        text(0, 6, C_TEXT, line);
        snprintf(line, sizeof line, "events %u %s%s", mac_events, mac_dry ? "DRY-RUN" : "LIVE",
                 (!mac_dry && !mac_ax) ? " no-AX!" : "");
        text(0, 7, mac_dry ? C_DIM : C_OK, line);
        snprintf(line, sizeof line, "tx %u  rx %u  err %d", tx_inputs, (unsigned)link.rx_frames, link_errors);
        text(0, 8, C_DIM, line);

        /* nub box */
        fill(8, 84, 68, 68, C_PANEL);
        fill(8 + 33, 84, 1, 68, C_DIM);
        fill(8, 84 + 33, 68, 1, C_DIM);
        fill(8 + pad.Lx * 64 / 255, 84 + pad.Ly * 64 / 255, 5, 5, C_ACCENT);
        snprintf(line, sizeof line, "nub %3d,%3d", pad.Lx, pad.Ly);
        text(11, 11, C_TEXT, line);
        snprintf(line, sizeof line, "btn %06X", (unsigned)pad.Buttons);
        text(11, 13, C_DIM, line);

        draw_button(1, 21, "L", pad.Buttons & PSP_CTRL_LTRIGGER);
        draw_button(4, 21, "R", pad.Buttons & PSP_CTRL_RTRIGGER);
        draw_button(7, 21, "UP", pad.Buttons & PSP_CTRL_UP);
        draw_button(10, 21, "DN", pad.Buttons & PSP_CTRL_DOWN);
        draw_button(13, 21, "LT", pad.Buttons & PSP_CTRL_LEFT);
        draw_button(16, 21, "RT", pad.Buttons & PSP_CTRL_RIGHT);
        draw_button(1, 23, "X", pad.Buttons & PSP_CTRL_CROSS);
        draw_button(3, 23, "O", pad.Buttons & PSP_CTRL_CIRCLE);
        draw_button(5, 23, "[]", pad.Buttons & PSP_CTRL_SQUARE);
        draw_button(8, 23, "/\\", pad.Buttons & PSP_CTRL_TRIANGLE);
        draw_button(11, 23, "SEL", pad.Buttons & PSP_CTRL_SELECT);
        draw_button(15, 23, "STA", pad.Buttons & PSP_CTRL_START);

        text(0, 26, C_DIM, "nub=mouse L/R=click");
        text(0, 27, C_DIM, "hold SELECT: wheel");
        text(0, 28, C_DIM, "/\\+nub = scroll");

        draw_wheel(wheel_open, hover);
        if (!have_config) textf_px(WCX - 60, WCY + WR + 6, C_ERR, "waiting for Mac");
        else if (wheel_open && hover != CTRL_NO_SLICE) {
            snprintf(line, sizeof line, "release: %s", labels[hover]);
            textf_px(WCX - (int)strlen(line) * 4, WCY + WR + 6, C_ACCENT, line);
        }

        fill(0, SCR_H - 12, SCR_W, 12, C_PANEL);
        text(0, 33, last_msg_color, last_msg[0] ? last_msg : "ready");

        sceDisplayWaitVblankStart();
        memcpy(VRAM, bb, sizeof bb);
        frame++;
    }
    if (dio.kind == DECK_IO_USB) psp_link_send(&link, PSP_LINK_T_BYE, 0, NULL, 0);
    sceKernelExitGame();
    return 0;
}
