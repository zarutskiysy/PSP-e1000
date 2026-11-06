/* echo: reference PSP app for the link. In PPSSPP it talks through the mailbox io
 * (tools/ppsspp_bridge.py); on hardware through USB (common/psp/usb, -DWITH_USB).
 * Answers HELLO/PING automatically, echoes every frame of type >= 0xF1, shows stats. */
#include <pspctrl.h>
#include <pspdebug.h>
#include <pspdisplay.h>
#include <pspkernel.h>
#include <string.h>

#include "../../common/psp/io_mailbox.h"
#include "../../common/psp/link.h"
#ifdef WITH_USB
#include "../../common/psp/usb/psp_usb_io.h"
#endif

PSP_MODULE_INFO("PSPE1000_ECHO", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);
PSP_HEAP_SIZE_KB(-1024);

static volatile int running = 1;
static int exit_cb(int a, int b, void *c) { (void)a; (void)b; (void)c; running = 0; return 0; }
static int cb_thread(SceSize args, void *argp) {
    (void)args; (void)argp;
    sceKernelRegisterExitCallback(sceKernelCreateCallback("exit", exit_cb, NULL));
    sceKernelSleepThreadCB();
    return 0;
}

static uint8_t mbox_mem[64 + 2 * 65536] __attribute__((aligned(64)));
static uint8_t rx[65536 + 1024], tx[65536 + 1024], chunk[16384];

int main(void) {
    psp_mbox_t mb;
    psp_link_t l;
    psp_link_frame_t f;
    psp_link_io_t io;
    const char *mode = "?";
    int err = 0;
    uint32_t echoed = 0, bytes = 0;
    SceUID th = sceKernelCreateThread("cb", cb_thread, 0x11, 0xFA0, 0, 0);
    if (th >= 0) sceKernelStartThread(th, 0, 0);
    pspDebugScreenInit();

    if (psp_is_emulator()) {
        psp_mbox_init(&mb, mbox_mem, sizeof mbox_mem, 65536, 65536);
        io = psp_mbox_io(&mb);
        mode = "emulator mailbox (run tools/ppsspp_bridge.py)";
    } else {
#ifdef WITH_USB
        err = psp_usb_start(PSP_USB_MODE_HOSTFS);
        io = psp_usb_io();
        mode = "USB hostfs (run usbhostfs_pc on the Mac)";
#else
        mode = "no transport (built without WITH_USB)";
        err = -1;
#endif
    }
    if (!err) {
        psp_link_init(&l, io, rx, sizeof rx, tx, sizeof tx, chunk, sizeof chunk);
        l.name = "echo";
    }
    while (running) {
        int r = err ? 0 : psp_link_poll(&l, 16000, &f);
        if (r == 1 && f.type >= 0xF1) {
            psp_link_send(&l, f.type, f.flags, f.payload, f.len);
            echoed++;
            bytes += f.len;
        }
        pspDebugScreenSetXY(0, 0);
        pspDebugScreenPrintf("PSP E1000 x Mac -- link echo\n\nmode: %s\nerr: %d\n", mode, err);
        if (!err) {
            pspDebugScreenPrintf("peer hello: %s (app %d)\nrx frames: %u  tx frames: %u\n", l.peer_hello ? "yes" : "no ",
                                 l.peer.app, (unsigned)l.rx_frames, (unsigned)l.tx_frames);
            pspDebugScreenPrintf("echoed: %u frames, %u bytes\ncrc errors: %u\n", (unsigned)echoed, (unsigned)bytes,
                                 (unsigned)l.parser.crc_errors);
        }
        if (r < 0) err = r;
    }
#ifdef WITH_USB
    psp_usb_stop();
#endif
    sceKernelExitGame();
    return 0;
}
