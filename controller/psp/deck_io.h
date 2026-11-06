/* deck_io.h — the ONE place where the PSP deck app picks its byte transport.
 *
 *   real PSP      -> USB, psplink usbhostfs async channel 4 (common/psp/usb/psp_usb_io.h, HOSTFS mode)
 *   PPSSPP        -> mailbox io (common/psp/io_mailbox.h) bridged to the Mac by tools/ppsspp_bridge.py;
 *                    if no bridge shows up within 6 s, the built-in demo peer takes over
 *   demo / fallback -> in-memory pipe to an in-process fake Mac (demo_peer.c): UI works with no Mac
 *
 * Hold TRIANGLE while the app starts to force demo mode (useful on hardware without a cable).
 * Everything above this layer only sees a psp_link_io_t.
 */
#ifndef DECK_IO_H
#define DECK_IO_H

#include "../../common/psp/link.h"

enum { DECK_IO_DEMO = 0, DECK_IO_MAILBOX = 1, DECK_IO_USB = 2 };

typedef struct {
    int kind;               /* DECK_IO_* */
    psp_link_io_t io;
    const char *name;       /* "demo", "ppsspp-mailbox", "usb-hostfs" */
    char note[96];          /* why this io was chosen / last error */
    int emulator;           /* 1 = running in PPSSPP */
} deck_io_t;

/* Chooses and opens the transport. Never fails: falls back to demo. */
void deck_io_open(deck_io_t *d, int force_demo);
/* Called once per frame (runs the demo peer). Returns 1 when the io was replaced (emulator without
 * a bridge falls back to the demo peer): the caller must re-init its psp_link_t with d->io. */
int deck_io_service(deck_io_t *d);
/* 1 when bytes can flow (USB host connected / always for demo and mailbox). */
int deck_io_ready(const deck_io_t *d);
/* USB debug line ("usb rx/tx bytes, last err"); empty string when not in USB mode. */
void deck_io_debug_line(const deck_io_t *d, char *out, int n);
/* Short status text for the UI. */
const char *deck_io_state_text(const deck_io_t *d);

#endif
