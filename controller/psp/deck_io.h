/* deck_io.h — the ONE place where the PSP deck app picks its byte transport.
 *
 *   real PSP      -> USB, psplink usbhostfs async channel 4 (common/psp/usb/psp_usb_io.h, HOSTFS mode)
 *   PPSSPP        -> mailbox io (common/psp/io_mailbox.h) bridged to the Mac by tools/ppsspp_bridge.py,
 *                    when that file exists at build time; otherwise the built-in demo peer
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
/* Called once per frame (runs the demo peer, refreshes USB state). */
void deck_io_service(deck_io_t *d);
/* 1 when bytes can flow (USB host connected / always for demo and mailbox). */
int deck_io_ready(const deck_io_t *d);
/* Short status text for the UI. */
const char *deck_io_state_text(const deck_io_t *d);

#endif
