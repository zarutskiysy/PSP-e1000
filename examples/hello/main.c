/* Hello world for PSP E1000 x Mac: proves the toolchain + PPSSPP pipeline and runs the shared
 * link logic (common/psp) over an in-memory pipe on the PSP CPU. */
#include <pspctrl.h>
#include <pspdebug.h>
#include <pspdisplay.h>
#include <pspkernel.h>
#include <psprtc.h>
#include <string.h>

#include "../../common/psp/io_pipe.h"
#include "../../common/psp/link.h"

PSP_MODULE_INFO("PSPE1000_HELLO", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);
PSP_HEAP_SIZE_KB(-1024);

static int running = 1;
static int exit_cb(int a, int b, void *c) {
    (void)a; (void)b; (void)c;
    running = 0;
    sceKernelExitGame();
    return 0;
}
static int cb_thread(SceSize args, void *argp) {
    (void)args; (void)argp;
    int cbid = sceKernelCreateCallback("exit", exit_cb, NULL);
    sceKernelRegisterExitCallback(cbid);
    sceKernelSleepThreadCB();
    return 0;
}

static int self_test(void) {
    static uint8_t a2b[2048], b2a[2048], rx_a[256], tx_a[256], ch_a[128], rx_b[256], tx_b[256], ch_b[128];
    psp_ring_t r1, r2;
    psp_pipe_end_t ea, eb;
    psp_link_t mac, psp;
    psp_link_frame_t f;
    psp_ring_init(&r1, a2b, sizeof a2b);
    psp_ring_init(&r2, b2a, sizeof b2a);
    ea.out = &r1; ea.in = &r2; eb.out = &r2; eb.in = &r1;
    psp_link_init(&mac, psp_pipe_io(&ea), rx_a, sizeof rx_a, tx_a, sizeof tx_a, ch_a, sizeof ch_a);
    psp_link_init(&psp, psp_pipe_io(&eb), rx_b, sizeof rx_b, tx_b, sizeof tx_b, ch_b, sizeof ch_b);
    if (psp_link_send_hello(&mac, PSP_LINK_T_HELLO, 0, "mac")) return -1;
    if (psp_link_poll(&psp, 0, &f) != 1 || f.type != PSP_LINK_T_HELLO) return -2;
    if (psp_link_poll(&mac, 0, &f) != 1 || f.type != PSP_LINK_T_HELLO_ACK) return -3;
    if (psp_link_send(&mac, PSP_LINK_T_PING, 0, "tick", 4)) return -4;
    if (psp_link_poll(&psp, 0, &f) != 1) return -5;
    if (psp_link_poll(&mac, 0, &f) != 1 || f.type != PSP_LINK_T_PONG || memcmp(f.payload, "tick", 4)) return -6;
    return 0;
}

int main(void) {
    SceUID th = sceKernelCreateThread("cb", cb_thread, 0x11, 0xFA0, 0, 0);
    if (th >= 0) sceKernelStartThread(th, 0, 0);
    pspDebugScreenInit();
    sceCtrlSetSamplingCycle(0);
    sceCtrlSetSamplingMode(PSP_CTRL_MODE_ANALOG);
    int st = self_test();
    int frame = 0;
    SceCtrlData pad;
    while (running) {
        sceCtrlPeekBufferPositive(&pad, 1);
        pspDebugScreenSetXY(0, 0);
        pspDebugScreenPrintf("PSP E1000 x Mac -- hello world\n\n");
        pspDebugScreenPrintf("toolchain: pspdev (psp-gcc 15.2)\n");
        pspDebugScreenPrintf("link self-test (HELLO/PING over pipe): %s (%d)\n\n", st == 0 ? "PASS" : "FAIL", st);
        pspDebugScreenPrintf("analog: x=%3d y=%3d  buttons=%08X\n", pad.Lx, pad.Ly, pad.Buttons);
        pspDebugScreenPrintf("frame: %d\n\nPress HOME to exit.\n", frame++);
        sceDisplayWaitVblankStart();
    }
    return 0;
}
