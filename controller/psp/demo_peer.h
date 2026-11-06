/* demo_peer.h — an in-process fake Mac on the other end of an in-memory pipe, so the deck UI
 * (wheel labels, action results, status) works in PPSSPP or on a PSP without a Mac. */
#ifndef DEMO_PEER_H
#define DEMO_PEER_H
#include "../../common/psp/link.h"

/* Returns the PSP-side io. */
psp_link_io_t demo_peer_open(void);
/* Pump the fake Mac once (call every frame). */
void demo_peer_step(void);
#endif
