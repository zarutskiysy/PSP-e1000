/* main.c — PSP platform layer for the Blackwater Ping console.
 * Picks the link io ONCE at startup (select_io), then runs the plain-C console (app.c/console.c)
 * and the software renderer (view.c/gfx.c) straight into a double-buffered 8888 framebuffer. */
#include <pspctrl.h>
#include <pspdisplay.h>
#include <pspge.h>
#include <pspiofilemgr.h>
#include <pspkernel.h>
#include <pspsdk.h>
#include <psputils.h>
#include <string.h>

#include "app.h"
#include "view.h"
#include "../../common/psp/io_mailbox.h"
#ifdef BW_HAVE_USB
#include "../../common/psp/usb/psp_usb_io.h"
#endif

PSP_MODULE_INFO("BLACKWATER_PING", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);
PSP_HEAP_SIZE_KB(-1024);

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

static bw_app_t app;
static char io_label[24];

static psp_mbox_t mbox;
static uint8_t mbox_mem[64 + 2 * 65536] __attribute__((aligned(64)));
static int mbox_peer(void *ctx) { return psp_mbox_bridge_seen((const psp_mbox_t *)ctx); }

static void select_io(uint16_t held) {
    if (held & BW_B_SELECT) { /* hold SELECT at boot: force the offline demo */
        bw_app_init_demo(&app);
        return;
    }
    if (psp_is_emulator()) {
        /* PPSSPP: tools/ppsspp_bridge.py moves bytes between this mailbox and a Mac TCP port */
        if (psp_mbox_init(&mbox, mbox_mem, sizeof mbox_mem, 65536, 65536) == 0) {
            mbox.write_timeout_us = 100000; /* never stall the frame loop for long */
            bw_app_init(&app, psp_mbox_io(&mbox), "EMU");
            app.peer_present = mbox_peer;
            app.peer_ctx = &mbox;
            return;
        }
    } else {
#ifdef BW_HAVE_USB
        int r = psp_usb_start(PSP_USB_MODE_HOSTFS);
        if (r >= 0) {
            bw_app_init(&app, psp_usb_io(), "USB");
            return;
        }
#endif
    }
    bw_app_init_demo(&app); /* no real link available: scripted demo Mac */
}

static uint16_t map_buttons(unsigned b) {
    uint16_t o = 0;
    if (b & PSP_CTRL_UP) o |= BW_B_UP;
    if (b & PSP_CTRL_DOWN) o |= BW_B_DOWN;
    if (b & PSP_CTRL_LEFT) o |= BW_B_LEFT;
    if (b & PSP_CTRL_RIGHT) o |= BW_B_RIGHT;
    if (b & PSP_CTRL_CROSS) o |= BW_B_CROSS;
    if (b & PSP_CTRL_CIRCLE) o |= BW_B_CIRCLE;
    if (b & PSP_CTRL_SQUARE) o |= BW_B_SQUARE;
    if (b & PSP_CTRL_TRIANGLE) o |= BW_B_TRIANGLE;
    if (b & PSP_CTRL_START) o |= BW_B_START;
    if (b & PSP_CTRL_SELECT) o |= BW_B_SELECT;
    if (b & PSP_CTRL_LTRIGGER) o |= BW_B_L;
    if (b & PSP_CTRL_RTRIGGER) o |= BW_B_R;
    return o;
}

static int8_t axis(unsigned char v) {
    int a = (int)v - 128;
    if (a < -127) a = -127;
    if (a > 127) a = 127;
    return (int8_t)a;
}

int main(void) {
    SceCtrlData pad;
    uint32_t *vram = (uint32_t *)sceGeEdramGetAddr(); /* 0x04000000, cached */
    uint32_t *bufs[2];
    int back = 1;
    bw_gfx_t g;
    SceUID th = sceKernelCreateThread("cb", cb_thread, 0x11, 0xFA0, 0, 0);
    if (th >= 0) sceKernelStartThread(th, 0, 0);

    bufs[0] = vram;
    bufs[1] = vram + BW_STRIDE * BW_SCREEN_H;
    memset(bufs[0], 0, BW_STRIDE * BW_SCREEN_H * 4);
    sceKernelDcacheWritebackAll();
    sceDisplaySetMode(0, BW_SCREEN_W, BW_SCREEN_H);
    sceDisplaySetFrameBuf(bufs[0], BW_STRIDE, PSP_DISPLAY_PIXEL_FORMAT_8888, PSP_DISPLAY_SETBUF_NEXTFRAME);

    sceCtrlSetSamplingCycle(0);
    sceCtrlSetSamplingMode(PSP_CTRL_MODE_ANALOG);
    sceCtrlPeekBufferPositive(&pad, 1);
    select_io(map_buttons(pad.Buttons));
    strncpy(io_label, app.io_name, sizeof io_label - 1);

    while (running) {
        uint32_t now = sceKernelGetSystemTimeLow() / 1000u;
        sceCtrlPeekBufferPositive(&pad, 1);
        bw_app_step(&app, now, map_buttons(pad.Buttons), axis(pad.Lx), axis(pad.Ly));
        if (app.io_dead && !app.demo) strncpy(io_label, "IO ERR", sizeof io_label - 1);
        g.px = bufs[back];
        bw_view_draw(&g, &app.con, io_label);
        sceKernelDcacheWritebackAll();
        sceDisplayWaitVblankStart();
        sceDisplaySetFrameBuf(bufs[back], BW_STRIDE, PSP_DISPLAY_PIXEL_FORMAT_8888, PSP_DISPLAY_SETBUF_IMMEDIATE);
        back ^= 1;
    }
#ifdef BW_HAVE_USB
    if (!app.demo && strcmp(app.io_name, "USB") == 0) psp_usb_stop();
#endif
    sceKernelExitGame();
    return 0;
}
