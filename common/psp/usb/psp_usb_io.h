/*
 * psp_usb_io.h — real-hardware USB transports for the PSP side (NOT available in PPSSPP:
 * PPSSPP does not emulate sceUsbbd*). Both return a psp_link_io_t usable with link.h.
 *
 * Mode HOSTFS (default for low-bandwidth tracks: controller, game)
 *   PSP: psplinkusb's usbhostfs.prx (BSD, built from common/psp/usbhostfs/) + our helper
 *        pspmaclink.prx (kernel) which starts the USB bus, the "USBHostFSDriver" and activates
 *        PID 0x01C9. Data goes through usbhostfs async channel 4 (ASYNC_USER).
 *   Mac: `usbhostfs_pc` (ships with the pspdev toolchain) exposes channel 4 as TCP
 *        127.0.0.1:10004 -> Mac transport spec "hostfs" (pspmac.transport).
 *
 * Mode MACLINK (for bandwidth: second screen)
 *   PSP: our own pspmaclink.prx registers a vendor-class USB driver ("PspMacLinkDriver"),
 *        bulk IN 0x81 / bulk OUT 0x02, PID 0x01CB.
 *   Mac: pyusb/libusb directly -> Mac transport spec "usb".
 *
 * Only one USB driver can be active at a time, and the Go!Cam uses the same port.
 *
 * Files the EBOOT expects next to it on the memory stick:
 *   pspmaclink.prx (both modes), usbhostfs.prx (HOSTFS mode).
 */
#ifndef PSP_USB_IO_H
#define PSP_USB_IO_H

#include "../link.h"

#ifdef __cplusplus
extern "C" {
#endif

enum { PSP_USB_MODE_HOSTFS = 1, PSP_USB_MODE_MACLINK = 2 };

enum {
    PSP_USB_STATE_OFF = 0,       /* not started */
    PSP_USB_STATE_WAITING = 1,   /* driver up, no cable / host not connected yet */
    PSP_USB_STATE_CONNECTED = 2  /* host enumerated the device (and for HOSTFS: usbhostfs_pc said HELLO) */
};

/* Loads the PRX(s) from the EBOOT's directory and starts USB in the given mode.
 * Returns 0 on success, <0 on error (error codes are the sce* return values, print them). */
int psp_usb_start(int mode);
/* Stops USB and unloads nothing (modules stay resident until exit). */
void psp_usb_stop(void);
/* PSP_USB_STATE_* */
int psp_usb_state(void);
/* io for link.h; valid after psp_usb_start() succeeded. */
psp_link_io_t psp_usb_io(void);
/* Debug counters: out[0] attach speed (1 full, 2 high; MACLINK only), out[1] rx bytes, out[2] tx bytes,
 * out[3] last sce error. Returns 0, or <0 if not started. */
int psp_usb_info(int out[4]);
/* Human-readable last error (static string). */
const char *psp_usb_last_error(void);

#ifdef __cplusplus
}
#endif
#endif
