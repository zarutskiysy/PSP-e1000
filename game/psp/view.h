#ifndef BW_VIEW_H
#define BW_VIEW_H
#include "console.h"
#include "gfx.h"
/* io_name: short label of the active transport ("USB", "EMU", "DEMO", "TCP"). */
void bw_view_draw(bw_gfx_t *g, const bw_console_t *c, const char *io_name);
#endif
