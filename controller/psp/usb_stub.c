/* usb_stub.c — linked only while common/psp/usb has no implementation (the Makefile picks it).
 * Lets the deck app build and run (demo/emulator modes) before the USB io lands on main. */
#include "../../common/psp/usb/psp_usb_io.h"

int psp_usb_start(int mode) {
    (void)mode;
    return -1;
}
void psp_usb_stop(void) {}
int psp_usb_state(void) { return PSP_USB_STATE_OFF; }
static int nowrite(void *c, const void *b, int n) { (void)c; (void)b; (void)n; return -1; }
static int noread(void *c, void *b, int n, int t) { (void)c; (void)b; (void)n; (void)t; return -1; }
psp_link_io_t psp_usb_io(void) {
    psp_link_io_t io = {nowrite, noread, 0};
    return io;
}
const char *psp_usb_last_error(void) { return "USB io not built in (usb_stub.c)"; }
