#include "deck_io.h"

#include <pspiofilemgr.h>
#include <stdio.h>
#include <string.h>

#include "../../common/psp/usb/psp_usb_io.h"
#include "demo_peer.h"

/* PPSSPP answers sceIoDevctl("kemulator:", EMULATOR_DEVCTL__IS_EMULATOR=3) (used by pspautotests);
 * real firmware has no such device and returns an error. Verified in PPSSPP 1.20.4 by the
 * status line of this app; the hardware branch is expected, not yet observed. */
static int detect_emulator(void) {
    unsigned int out = 0;
    int r = sceIoDevctl("kemulator:", 3, NULL, 0, &out, sizeof out);
    return r >= 0;
}

static void use_demo(deck_io_t *d, const char *why) {
    d->kind = DECK_IO_DEMO;
    d->name = "demo";
    d->io = demo_peer_open();
    snprintf(d->note, sizeof d->note, "%s", why);
}

void deck_io_open(deck_io_t *d, int force_demo) {
    memset(d, 0, sizeof *d);
    d->emulator = detect_emulator();
    if (force_demo) {
        use_demo(d, "TRIANGLE held at start: demo mode");
        return;
    }
    if (d->emulator) {
#ifdef DECK_HAVE_MAILBOX
        if (deck_mailbox_open(d) == 0) return;
#endif
        use_demo(d, "PPSSPP: no USB; built-in demo Mac");
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

void deck_io_service(deck_io_t *d) {
    if (d->kind == DECK_IO_DEMO) demo_peer_step();
}

int deck_io_ready(const deck_io_t *d) {
    if (d->kind == DECK_IO_USB) return psp_usb_state() == PSP_USB_STATE_CONNECTED;
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
    return d->kind == DECK_IO_MAILBOX ? "emulator bridge" : "demo (no Mac)";
}
