#include "deck_io.h"

#include <stdio.h>
#include <string.h>

#include <pspthreadman.h>

#include "../../common/psp/io_mailbox.h"
#include "../../common/psp/usb/psp_usb_io.h"
#include "demo_peer.h"

#define BRIDGE_GRACE_US 6000000u /* emulator: no bridge after this long -> built-in demo peer */

static uint8_t mbox_mem[64 + 2 * 16384] __attribute__((aligned(64)));
static psp_mbox_t mbox;
static unsigned t_open;

static void use_demo(deck_io_t *d, const char *why) {
    d->kind = DECK_IO_DEMO;
    d->name = "demo";
    d->io = demo_peer_open();
    snprintf(d->note, sizeof d->note, "%s", why);
}

void deck_io_open(deck_io_t *d, int force_demo) {
    memset(d, 0, sizeof *d);
    d->emulator = psp_is_emulator();
    t_open = sceKernelGetSystemTimeLow();
    if (force_demo) {
        use_demo(d, "TRIANGLE held at start: demo mode");
        return;
    }
    if (d->emulator) {
        if (psp_mbox_init(&mbox, mbox_mem, sizeof mbox_mem, 16384, 16384) == 0) {
            mbox.write_timeout_us = 0; /* never stall the UI if the bridge is gone */
            d->kind = DECK_IO_MAILBOX;
            d->name = "ppsspp-mailbox";
            d->io = psp_mbox_io(&mbox);
            snprintf(d->note, sizeof d->note, "PPSSPP: run tools/ppsspp_bridge.py");
            return;
        }
        use_demo(d, "PPSSPP: mailbox init failed; demo Mac");
        return;
    }
    {
        int r = psp_usb_start(PSP_USB_MODE_HOSTFS);
        if (r < 0) {
            char why[96];
            snprintf(why, sizeof why, "USB failed %08X: %.60s", (unsigned)r, psp_usb_last_error());
            use_demo(d, why);
            return;
        }
        d->kind = DECK_IO_USB;
        d->name = "usb-hostfs";
        d->io = psp_usb_io();
        snprintf(d->note, sizeof d->note, "usbhostfs ch4; run usbhostfs_pc + psp_deck on the Mac");
    }
}

int deck_io_service(deck_io_t *d) {
    if (d->kind == DECK_IO_DEMO) demo_peer_step();
    if (d->kind == DECK_IO_MAILBOX && !psp_mbox_bridge_seen(&mbox) &&
        sceKernelGetSystemTimeLow() - t_open > BRIDGE_GRACE_US) {
        use_demo(d, "PPSSPP: no bridge after 6 s; demo Mac");
        return 1;
    }
    return 0;
}

int deck_io_ready(const deck_io_t *d) {
    if (d->kind == DECK_IO_USB) return psp_usb_state() == PSP_USB_STATE_CONNECTED;
    if (d->kind == DECK_IO_MAILBOX) return psp_mbox_bridge_seen(&mbox);
    return 1;
}

const char *deck_io_state_text(const deck_io_t *d) {
    if (d->kind == DECK_IO_USB) {
        switch (psp_usb_state()) {
        case PSP_USB_STATE_CONNECTED: return "USB connected";
        case PSP_USB_STATE_WAITING: return "USB waiting for host";
        default: return "USB off";
        }
    }
    if (d->kind == DECK_IO_MAILBOX) return psp_mbox_bridge_seen(&mbox) ? "bridge up" : "wait bridge";
    return "demo, no Mac";
}

void deck_io_debug_line(const deck_io_t *d, char *out, int n) {
    int info[4] = {0, 0, 0, 0};
    out[0] = 0;
    if (d->kind != DECK_IO_USB || psp_usb_info(info) < 0) return;
    snprintf(out, n, "usb rx %d tx %d err %08X", info[1], info[2], (unsigned)info[3]);
}
