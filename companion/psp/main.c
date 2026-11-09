/* main.c — PSP platform layer for the AI Companion.
 *
 * Two threads, so USB can never stall the animation:
 *   - the main thread draws at vblank rate and owns all state (app.c, pet.c, ui.c);
 *   - the I/O thread owns the link: it may sit in a blocking USB call for seconds without
 *     the face noticing. They share only two lock-free single-producer/single-consumer rings. */
#include <pspctrl.h>
#include <pspdisplay.h>
#include <pspge.h>
#include <pspiofilemgr.h>
#include <pspkernel.h>
#include <psppower.h>
#include <pspsdk.h>
#include <psputils.h>
#include <stdio.h>
#include <string.h>

#include "../../common/psp/io_mailbox.h"
#include "../../common/psp/link.h"
#include "app.h"
#include "gfx.h"
#include "pet.h"
#include "ui.h"
#ifdef WITH_USB
#include "../../common/psp/usb/psp_usb_io.h"
#endif

PSP_MODULE_INFO("PSP_AI_COMPANION", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);
PSP_HEAP_SIZE_KB(-1024);

#define INT_LINK_DOWN 0xFEu /* internal ring message: link lost */
#define RX_SLOTS 32u
#define TX_SLOTS 16u
#define TX_MSG_MAX 16u

typedef struct {
    uint8_t type;
    uint16_t len;
    uint8_t data[PC_MAX_PAYLOAD];
} rx_msg_t;
typedef struct {
    uint8_t type, len;
    uint8_t data[TX_MSG_MAX];
} tx_msg_t;

static rx_msg_t rx_ring[RX_SLOTS];
static tx_msg_t tx_ring[TX_SLOTS];
static volatile uint32_t rx_head, rx_tail, tx_head, tx_tail;

static volatile int g_running = 1;
static volatile int g_io_stopped = 0;
static volatile int g_transport_ready = 0;
static uint32_t g_boot_id;

static psp_link_t g_link;
static uint8_t g_rx_payload[PC_MAX_PAYLOAD];
static uint8_t g_tx_buf[PC_MAX_PAYLOAD + PSP_LINK_OVERHEAD];
static uint8_t g_rx_chunk[4096];

static psp_mbox_t g_mbox;
static uint8_t g_mbox_mem[64 + 2 * 16384] __attribute__((aligned(64)));
static int g_emulator;
static const char *g_io_name = "none";
static char g_io_note[80];

static app_t g_app;
static pet_t g_pet;
static ui_view_t g_view;

static uint32_t now_ms(void) { return (uint32_t)(sceKernelGetSystemTimeWide() / 1000u); }

static int exit_cb(int a, int b, void *c) {
    (void)a; (void)b; (void)c;
    g_running = 0;
    return 0;
}
static int cb_thread(SceSize args, void *argp) {
    (void)args; (void)argp;
    sceKernelRegisterExitCallback(sceKernelCreateCallback("exit", exit_cb, NULL));
    sceKernelSleepThreadCB();
    return 0;
}

/* Main thread -> I/O thread. Never blocks the frame: a full ring returns -1 and the caller retries or reports. */
static int emit_to_io(void *ctx, uint8_t type, const void *payload, uint32_t len) {
    uint32_t next = (tx_head + 1) % TX_SLOTS;
    (void)ctx;
    if (next == tx_tail || len > TX_MSG_MAX) return -1;
    tx_ring[tx_head].type = type;
    tx_ring[tx_head].len = (uint8_t)len;
    memcpy(tx_ring[tx_head].data, payload, len);
    tx_head = next;
    return 0;
}

/* I/O thread -> main thread. Waits for room rather than dropping: nothing here is safe to lose. */
static void push_rx(uint8_t type, const uint8_t *p, uint32_t len) {
    uint32_t next = (rx_head + 1) % RX_SLOTS;
    if (len > PC_MAX_PAYLOAD) return;
    while (next == rx_tail && g_running) sceKernelDelayThread(2000);
    rx_ring[rx_head].type = type;
    rx_ring[rx_head].len = (uint16_t)len;
    if (len) memcpy(rx_ring[rx_head].data, p, len);
    rx_head = next;
}

static int transport_ready(void) {
    if (g_emulator) return psp_mbox_bridge_seen(&g_mbox);
#ifdef WITH_USB
    return psp_usb_state() == PSP_USB_STATE_CONNECTED;
#else
    return 0;
#endif
}

static void link_lost(int *up) {
    if (*up) {
        *up = 0;
        push_rx(INT_LINK_DOWN, NULL, 0);
    }
    g_link.peer_hello = 0;
    psp_link_parser_reset(&g_link.parser);
    g_link.rx_have = g_link.rx_off = 0;
    /* whatever the UI queued is for a link that no longer exists */
    tx_tail = tx_head;
}

static void send_heartbeat(uint32_t now) {
    uint8_t b[9];
    b[0] = PC_VERSION;
    psp_link_put_u32(b + 1, g_boot_id);
    psp_link_put_u32(b + 5, now);
    psp_link_send(&g_link, PC_T_HEARTBEAT, 0, b, sizeof b);
}

static int io_thread(SceSize args, void *argp) {
    uint32_t last_rx = 0, last_hb = 0;
    int up = 0;
    (void)args; (void)argp;
    while (g_running) {
        psp_link_frame_t f;
        uint32_t now = now_ms();
        int r;
        if (!g_transport_ready) {
            sceKernelDelayThread(50000);
            continue;
        }
        if (!transport_ready()) {
            link_lost(&up);
            sceKernelDelayThread(30000);
            continue;
        }
        if (g_link.peer_hello) {
            while (tx_tail != tx_head) {
                tx_msg_t *m = &tx_ring[tx_tail];
                if (psp_link_send(&g_link, m->type, 0, m->data, m->len) < 0) break;
                tx_tail = (tx_tail + 1) % TX_SLOTS;
            }
            if ((int32_t)(now - last_hb) >= 1000) {
                send_heartbeat(now);
                last_hb = now;
            }
        }
        r = psp_link_poll(&g_link, 12000, &f);
        if (r < 0) {
            link_lost(&up);
            sceKernelDelayThread(30000);
            continue;
        }
        if (r == 1) {
            last_rx = now_ms();
            if (f.type == PSP_LINK_T_HELLO || f.type == PSP_LINK_T_HELLO_ACK) {
                up = 1;
                last_hb = 0;
                push_rx(f.type, f.payload, 0);
            } else if (f.type == PSP_LINK_T_BYE) {
                link_lost(&up);
            } else if (f.type >= PC_T_CONN && f.type <= PC_T_HEARTBEAT && up) {
                push_rx(f.type, f.payload, f.len);
            }
        } else if (up && (int32_t)(now - last_rx) >= (int32_t)APP_LINK_TIMEOUT_MS) {
            link_lost(&up);
        }
    }
    g_io_stopped = 1;
    return 0;
}

static void open_transport(void) {
    psp_link_io_t io;
    g_emulator = psp_is_emulator();
    memset(&io, 0, sizeof io);
    if (g_emulator) {
        if (psp_mbox_init(&g_mbox, g_mbox_mem, sizeof g_mbox_mem, 16384, 16384) != 0) {
            snprintf(g_io_note, sizeof g_io_note, "Mailbox init failed");
            return;
        }
        g_mbox.write_timeout_us = 100000;
        io = psp_mbox_io(&g_mbox);
        g_io_name = "ppsspp-mailbox";
        snprintf(g_io_note, sizeof g_io_note, "Waiting for Mac (ppsspp_bridge)...");
    } else {
#ifdef WITH_USB
        int r = psp_usb_start(PSP_USB_MODE_MACLINK);
        if (r < 0) {
            snprintf(g_io_note, sizeof g_io_note, "USB failed %08X %.48s", (unsigned)r, psp_usb_last_error());
            return;
        }
        io = psp_usb_io();
        g_io_name = "usb-maclink";
        snprintf(g_io_note, sizeof g_io_note, "Waiting for Mac...");
#else
        snprintf(g_io_note, sizeof g_io_note, "Built without USB (USB=0)");
        return;
#endif
    }
    psp_link_init(&g_link, io, g_rx_payload, sizeof g_rx_payload, g_tx_buf, sizeof g_tx_buf, g_rx_chunk, sizeof g_rx_chunk);
    g_link.app = PC_APP_ID;
    g_link.name = "psp-companion";
    g_transport_ready = 1;
}

static uint32_t map_buttons(unsigned b) {
    uint32_t o = 0;
    if (b & PSP_CTRL_UP) o |= PC_BTN_UP;
    if (b & PSP_CTRL_DOWN) o |= PC_BTN_DOWN;
    if (b & PSP_CTRL_LEFT) o |= PC_BTN_LEFT;
    if (b & PSP_CTRL_RIGHT) o |= PC_BTN_RIGHT;
    if (b & PSP_CTRL_CROSS) o |= PC_BTN_CROSS;
    if (b & PSP_CTRL_CIRCLE) o |= PC_BTN_CIRCLE;
    if (b & PSP_CTRL_SQUARE) o |= PC_BTN_SQUARE;
    if (b & PSP_CTRL_TRIANGLE) o |= PC_BTN_TRIANGLE;
    if (b & PSP_CTRL_START) o |= PC_BTN_START;
    if (b & PSP_CTRL_SELECT) o |= PC_BTN_SELECT;
    if (b & PSP_CTRL_LTRIGGER) o |= PC_BTN_L;
    if (b & PSP_CTRL_RTRIGGER) o |= PC_BTN_R;
    return o;
}

static void drain_rx(uint32_t now) {
    while (rx_tail != rx_head) {
        rx_msg_t *m = &rx_ring[rx_tail];
        if (m->type == INT_LINK_DOWN) app_on_link(&g_app, 0, now);
        else app_on_frame(&g_app, m->type, m->data, m->len, now);
        rx_tail = (rx_tail + 1) % RX_SLOTS;
    }
}

int main(void) {
    uint32_t *vram = (uint32_t *)sceGeEdramGetAddr();
    uint32_t *bufs[2];
    int back = 1, slow_frames = 0, fast_frames = 0;
    uint32_t last_tick = 0;
    uint64_t prev;
    float fps = 60.0f, frame_ms = 0.0f;
    SceCtrlData pad;
    ui_stats_t st;
    SceUID th = sceKernelCreateThread("cb", cb_thread, 0x11, 0xFA0, 0, 0);
    SceUID io_th;
    if (th >= 0) sceKernelStartThread(th, 0, 0);

    scePowerSetClockFrequency(333, 333, 166);
    g_boot_id = sceKernelGetSystemTimeLow() | 1u;

    bufs[0] = vram;
    bufs[1] = vram + GFX_STRIDE * GFX_H;
    memset(bufs[0], 0, GFX_STRIDE * GFX_H * 4);
    memset(bufs[1], 0, GFX_STRIDE * GFX_H * 4);
    sceKernelDcacheWritebackAll();
    sceDisplaySetMode(0, GFX_W, GFX_H);
    sceDisplaySetFrameBuf(bufs[0], GFX_STRIDE, PSP_DISPLAY_PIXEL_FORMAT_8888, PSP_DISPLAY_SETBUF_NEXTFRAME);
    sceCtrlSetSamplingCycle(0);
    sceCtrlSetSamplingMode(PSP_CTRL_MODE_ANALOG);

    app_init(&g_app, emit_to_io, NULL);
    pet_init(&g_pet, g_boot_id);
    ui_init(&g_view);

    open_transport();
    if (g_io_note[0]) app_set_note(&g_app, g_io_note);

    /* The I/O thread runs above the render thread so input and acks are prompt; it sleeps in every
     * wait, so it only ever takes the slices it uses. */
    io_th = sceKernelCreateThread("io", io_thread, 0x18, 0x8000, 0, 0);
    if (io_th >= 0) sceKernelStartThread(io_th, 0, 0);

    prev = sceKernelGetSystemTimeWide();
    memset(&st, 0, sizeof st);
    while (g_running) {
        uint64_t t0 = sceKernelGetSystemTimeWide();
        float dt = (float)(t0 - prev) / 1000000.0f;
        uint32_t now = (uint32_t)(t0 / 1000u);
        prev = t0;
        if (dt > .1f) dt = .1f;

        /* A pet on a desk gets no button presses: without this the backlight and suspend timers expire. */
        if ((int32_t)(now - last_tick) >= 2000) {
            scePowerTick(PSP_POWER_TICK_ALL);
            last_tick = now;
        }
        drain_rx(now);
        sceCtrlPeekBufferPositive(&pad, 1);
        app_on_buttons(&g_app, map_buttons(pad.Buttons), now);
        app_tick(&g_app, now);

        pet_set_state(&g_pet, app_pet_state(&g_app));
        if (g_app.pending_anim) {
            pet_play(&g_pet, g_app.pending_anim);
            g_app.pending_anim = PC_ANIM_NONE;
        }
        pet_update(&g_pet, dt);
        ui_update(&g_view, &g_app, dt);

        st.fps = fps;
        st.frame_ms = frame_ms;
        st.rx_frames = g_link.rx_frames;
        st.tx_frames = g_link.tx_frames;
        st.crc_errors = g_link.parser.crc_errors;
        st.junk = g_link.parser.junk_bytes;
        st.io_name = g_io_name;
        st.quality = g_pet.quality;

        gfx_begin(bufs[back]);
        ui_draw(&g_view, &g_app, &g_pet, &st, now);
        sceKernelDcacheWritebackAll();

        {
            float ms = (float)(sceKernelGetSystemTimeWide() - t0) / 1000.0f;
            frame_ms += (ms - frame_ms) * .08f;
            /* Protect the frame rate on real hardware: shed the outer glow if we keep running late. */
            if (ms > 15.0f) {
                if (++slow_frames > 30) {
                    g_pet.quality = 0;
                    slow_frames = 0;
                }
            } else if (slow_frames > 0) {
                slow_frames--;
            }
            /* ...and restore it once there is clearly room again. */
            if (frame_ms < 8.0f) {
                if (++fast_frames > 300) {
                    g_pet.quality = 1;
                    fast_frames = 0;
                }
            } else {
                fast_frames = 0;
            }
            if (dt > .0005f) fps += (1.0f / dt - fps) * .05f;
        }

        sceDisplayWaitVblankStart();
        sceDisplaySetFrameBuf(bufs[back], GFX_STRIDE, PSP_DISPLAY_PIXEL_FORMAT_8888, PSP_DISPLAY_SETBUF_IMMEDIATE);
        back ^= 1;
    }

    {
        int waited = 0;
        while (!g_io_stopped && waited < 500) {
            sceKernelDelayThread(1000);
            waited++;
        }
    }
#ifdef WITH_USB
    if (!g_emulator) psp_usb_stop();
#endif
    sceKernelExitGame();
    return 0;
}
