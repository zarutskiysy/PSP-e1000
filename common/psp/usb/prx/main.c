/*
 * pspmaclink.prx — kernel-mode USB helper for PSP E1000 x Mac.
 *
 * Two modes (see ../psp_usb_io.h):
 *  - PML_MODE_HOSTFS:  starts psplink's "USBHostFSDriver" (usbhostfs.prx, loaded first) and moves our
 *                      byte stream over its async channel 4 (Mac: `usbhostfs_pc`, TCP 10004).
 *  - PML_MODE_MACLINK: registers our own vendor-class driver "PspMacLinkDriver" with one bulk IN
 *                      (0x81) and one bulk OUT (0x02) endpoint, PID 0x1CB (Mac: pyusb/libusb).
 *
 * The descriptor / request code follows psplinkusb's usbhostfs/main.c (BSD-3-Clause, (c) 2006 James F,
 * https://github.com/pspdev/psplinkusb), simplified to a raw byte pipe.
 *
 * Zero-length-packet rule: a bulk transfer whose length is a multiple of the max packet size does
 * not end with a short packet, so the other side would wait for more. Both ends therefore split such
 * writes into (len-1, 1). The receive side always posts 64 KiB requests (a multiple of 512).
 *
 * UNTESTED ON HARDWARE (built 2026-11-07 without a PSP attached). PPSSPP does not emulate sceUsbbd.
 */
#include <pspkernel.h>
#include <pspsdk.h>
#include <pspusb.h>
#include <pspusbbus.h>
#include <string.h>

#include "../../usbhostfs/usbasync.h"
#include "pspmaclink.h"

PSP_MODULE_INFO("PspMacLink", PSP_MODULE_KERNEL, 1, 0);

#define BUF_SIZE (64 * 1024)
#define EV_ATTACH 1
#define EV_DETACH 2
#define EV_TX_DONE 4
#define EV_RX_DONE 8

static int g_mode = 0;
static volatile int g_state = 0; /* 0 off, 1 waiting, 2 connected */
static volatile int g_speed = 0;
static int g_registered = 0;
static int g_last_err = 0;
static unsigned int g_rx_bytes = 0, g_tx_bytes = 0;
static SceUID g_ev = -1;
static SceUID g_txsema = -1, g_rxsema = -1;

static unsigned char g_txbuf[BUF_SIZE] __attribute__((aligned(64)));
static unsigned char g_rxbuf[BUF_SIZE] __attribute__((aligned(64)));
static int g_rx_have = 0, g_rx_off = 0, g_rx_pending = 0;
static struct UsbdDeviceReq g_txreq, g_rxreq;
static struct AsyncEndpoint g_async; /* HOSTFS mode: channel 4 ring (kernel memory) */

/* ---------------- descriptors (MACLINK mode) ---------------- */
static struct DeviceDescriptor devdesc_hi = {18, 1, 0x200, 0, 0, 0, 64, 0, 0, 0x100, 0, 0, 0, 1};
static struct DeviceDescriptor devdesc_full = {18, 1, 0x200, 0, 0, 0, 64, 0, 0, 0x100, 0, 0, 0, 1};
static struct ConfigDescriptor confdesc_hi = {9, 2, (9 + 9 + 2 * 7), 1, 1, 0, 0xC0, 0};
static struct ConfigDescriptor confdesc_full = {9, 2, (9 + 9 + 2 * 7), 1, 1, 0, 0xC0, 0};
static struct InterfaceDescriptor interdesc_hi = {9, 4, 0, 0, 2, 0xFF, 0x1, 0xFF, 1};
static struct InterfaceDescriptor interdesc_full = {9, 4, 0, 0, 2, 0xFF, 0x1, 0xFF, 1};
static struct EndpointDescriptor endpdesc_hi[2] = {{7, 5, 0x81, 2, 512, 0}, {7, 5, 0x02, 2, 512, 0}};
static struct EndpointDescriptor endpdesc_full[2] = {{7, 5, 0x81, 2, 64, 0}, {7, 5, 0x02, 2, 64, 0}};
static unsigned char strp[] = {0x8, 0x3, '<', 0, '>', 0, 0, 0};
static struct UsbEndpoint endp[3] = {{0, 0, 0}, {1, 0, 0}, {2, 0, 0}};
static struct UsbInterface intp = {0xFFFFFFFF, 0, 1};
static struct UsbData usbdata[2];

static int usb_request(int arg1, int arg2, struct DeviceRequest *req) {
    (void)arg1; (void)arg2; (void)req;
    return 0;
}
static int func28(int a, int b, int c) {
    (void)a; (void)b; (void)c;
    return 0;
}
static int usb_attach(int speed, void *a2, void *a3) {
    (void)a2; (void)a3;
    g_speed = speed;
    g_state = 2;
    sceKernelSetEventFlag(g_ev, EV_ATTACH);
    return 0;
}
static int usb_detach(int a1, int a2, int a3) {
    (void)a1; (void)a2; (void)a3;
    g_state = 1;
    g_rx_pending = 0;
    g_rx_have = g_rx_off = 0;
    sceKernelSetEventFlag(g_ev, EV_DETACH);
    return 0;
}

static void fill_usbdata(struct UsbData *d, struct DeviceDescriptor *dev, struct ConfigDescriptor *conf,
                         struct InterfaceDescriptor *inter, struct EndpointDescriptor *ep) {
    memcpy(d->devdesc, dev, sizeof(*dev));
    d->config.pconfdesc = &d->confdesc;
    d->config.pinterfaces = &d->interfaces;
    d->config.pinterdesc = &d->interdesc;
    d->config.pendp = d->endp;
    memcpy(d->confdesc.desc, conf, sizeof(*conf));
    d->confdesc.pinterfaces = &d->interfaces;
    d->interfaces.pinterdesc[0] = &d->interdesc;
    d->interfaces.intcount = 1;
    memcpy(d->interdesc.desc, inter, sizeof(*inter));
    d->interdesc.pendp = d->endp;
    memcpy(d->endp[0].desc, &ep[0], sizeof(ep[0]));
    memcpy(d->endp[1].desc, &ep[1], sizeof(ep[1]));
}

extern struct UsbDriver g_driver;

static int start_func(int size, void *p) {
    (void)size; (void)p;
    memset(usbdata, 0, sizeof(usbdata));
    fill_usbdata(&usbdata[0], &devdesc_hi, &confdesc_hi, &interdesc_hi, endpdesc_hi);
    fill_usbdata(&usbdata[1], &devdesc_full, &confdesc_full, &interdesc_full, endpdesc_full);
    g_driver.devp_hi = usbdata[0].devdesc;
    g_driver.confp_hi = &usbdata[0].config;
    g_driver.devp = usbdata[1].devdesc;
    g_driver.confp = &usbdata[1].config;
    return 0;
}
static int stop_func(int size, void *p) {
    (void)size; (void)p;
    return 0;
}

struct UsbDriver g_driver = {
    PML_DRIVER_NAME, 3, endp, &intp, NULL, NULL, NULL, NULL, (struct StringDescriptor *)strp,
    usb_request, func28, usb_attach, usb_detach, 0, start_func, stop_func, NULL};

static int tx_done(struct UsbdDeviceReq *req, int a2, int a3) {
    (void)req; (void)a2; (void)a3;
    sceKernelSetEventFlag(g_ev, EV_TX_DONE);
    return 0;
}
static int rx_done(struct UsbdDeviceReq *req, int a2, int a3) {
    (void)req; (void)a2; (void)a3;
    sceKernelSetEventFlag(g_ev, EV_RX_DONE);
    return 0;
}

/* ---------------- MACLINK bulk I/O ---------------- */
static int bulk_send(const unsigned char *data, int len) {
    u32 res;
    SceUInt to = 2000000;
    int r;
    sceKernelDcacheWritebackRange(data, len);
    memset(&g_txreq, 0, sizeof(g_txreq));
    g_txreq.endp = &endp[1];
    g_txreq.data = (void *)data;
    g_txreq.size = len;
    g_txreq.func = tx_done;
    sceKernelClearEventFlag(g_ev, ~EV_TX_DONE);
    r = sceUsbbdReqSend(&g_txreq);
    if (r < 0) return r;
    r = sceKernelWaitEventFlag(g_ev, EV_TX_DONE, PSP_EVENT_WAITOR | PSP_EVENT_WAITCLEAR, &res, &to);
    if (r < 0) {
        sceUsbbdReqCancelAll(&endp[1]);
        return r;
    }
    if (g_txreq.retcode != 0) return -1;
    return g_txreq.recvsize;
}

static int maclink_write(const unsigned char *data, int len) {
    int done = 0;
    int mps = g_speed == 2 ? 512 : 64;
    while (done < len) {
        int n = len - done, r;
        if (n > BUF_SIZE) n = BUF_SIZE;
        if (n % mps == 0 && n > 1) n -= 1; /* never end a transfer on a full packet (see header) */
        memcpy(g_txbuf, data + done, n);
        r = bulk_send(g_txbuf, n);
        if (r <= 0) return r < 0 ? r : -1;
        done += r;
        g_tx_bytes += r;
    }
    return done;
}

static int maclink_read(unsigned char *data, int len, int timeout_us) {
    u32 res;
    int r;
    if (g_rx_off < g_rx_have) {
        int n = g_rx_have - g_rx_off;
        if (n > len) n = len;
        memcpy(data, g_rxbuf + g_rx_off, n);
        g_rx_off += n;
        return n;
    }
    if (!g_rx_pending) {
        sceKernelDcacheInvalidateRange(g_rxbuf, BUF_SIZE);
        memset(&g_rxreq, 0, sizeof(g_rxreq));
        g_rxreq.endp = &endp[2];
        g_rxreq.data = g_rxbuf;
        g_rxreq.size = BUF_SIZE;
        g_rxreq.func = rx_done;
        sceKernelClearEventFlag(g_ev, ~EV_RX_DONE);
        r = sceUsbbdReqRecv(&g_rxreq);
        if (r < 0) return r;
        g_rx_pending = 1;
    }
    {
        SceUInt to = timeout_us < 0 ? 0 : (SceUInt)timeout_us;
        r = sceKernelWaitEventFlag(g_ev, EV_RX_DONE, PSP_EVENT_WAITOR | PSP_EVENT_WAITCLEAR, &res,
                                   timeout_us < 0 ? NULL : &to);
    }
    if (r < 0) return 0; /* timeout: the request stays queued, picked up next call */
    g_rx_pending = 0;
    if (g_rxreq.retcode != 0 || g_rxreq.recvsize <= 0) return g_rxreq.retcode == -3 ? -1 : 0;
    g_rx_have = g_rxreq.recvsize;
    g_rx_off = 0;
    g_rx_bytes += g_rx_have;
    return maclink_read(data, len, 0);
}

/* ---------------- exported syscalls ---------------- */
int pmlStart(int mode) {
    int k1 = pspSdkSetK1(0), r;
    do {
        if (g_mode) { r = 0x80000001; break; } /* already started */
        r = sceUsbStart(PSP_USBBUS_DRIVERNAME, 0, 0);
        if (r < 0 && r != (int)0x80243002 /* already started */) break;
        if (mode == PML_MODE_HOSTFS) {
            /* Order as in psplinkusb tools/remotejoy: start driver, activate, THEN register the async
             * channel (usbhostfs's start_func clears all channel registrations). */
            r = sceUsbStart("USBHostFSDriver", 0, 0);
            if (r < 0) break;
            g_state = 1;
            r = sceUsbActivate(PML_PID_HOSTFS);
            if (r < 0) break;
            memset(&g_async, 0, sizeof(g_async));
            r = usbAsyncRegister(ASYNC_USER, &g_async);
        } else if (mode == PML_MODE_MACLINK) {
            if (!g_registered) {
                r = sceUsbbdRegister(&g_driver);
                if (r < 0) break;
                g_registered = 1;
            }
            r = sceUsbStart(PML_DRIVER_NAME, 0, 0);
            if (r < 0) break;
            g_state = 1; /* before activate: the attach callback may fire right away and set 2 */
            r = sceUsbActivate(PML_PID_MACLINK);
        } else {
            r = 0x80000002;
            break;
        }
        if (r < 0) break;
        g_mode = mode;
        r = 0;
    } while (0);
    if (r < 0) {
        g_last_err = r;
        g_state = 0;
    }
    pspSdkSetK1(k1);
    return r;
}

int pmlStop(void) {
    int k1 = pspSdkSetK1(0);
    if (g_mode == PML_MODE_HOSTFS) {
        sceUsbDeactivate(PML_PID_HOSTFS);
        sceUsbStop("USBHostFSDriver", 0, 0);
        usbAsyncUnregister(ASYNC_USER);
    } else if (g_mode == PML_MODE_MACLINK) {
        sceUsbbdReqCancelAll(&endp[1]);
        sceUsbbdReqCancelAll(&endp[2]);
        sceUsbDeactivate(PML_PID_MACLINK);
        sceUsbStop(PML_DRIVER_NAME, 0, 0);
    }
    if (g_mode) sceUsbStop(PSP_USBBUS_DRIVERNAME, 0, 0);
    g_mode = 0;
    g_state = 0;
    pspSdkSetK1(k1);
    return 0;
}

int pmlState(void) {
    int k1 = pspSdkSetK1(0), s = g_state;
    if (g_mode == PML_MODE_HOSTFS) s = (sceUsbGetState() & PSP_USB_CONNECTION_ESTABLISHED) ? 2 : 1;
    pspSdkSetK1(k1);
    return s;
}

int pmlWrite(const void *data, int len) {
    int k1 = pspSdkSetK1(0), r;
    if (len < 0 || !data) {
        pspSdkSetK1(k1);
        return -1;
    }
    if (g_mode == PML_MODE_HOSTFS) {
        r = usbAsyncWrite(ASYNC_USER, data, len);
        if (r > 0) g_tx_bytes += r;
    } else if (g_mode == PML_MODE_MACLINK && g_state == 2) {
        sceKernelWaitSema(g_txsema, 1, NULL);
        r = maclink_write((const unsigned char *)data, len);
        sceKernelSignalSema(g_txsema, 1);
    } else {
        r = -2; /* not connected */
    }
    if (r < 0) g_last_err = r;
    pspSdkSetK1(k1);
    return r;
}

int pmlRead(void *data, int len, int timeout_us) {
    int k1 = pspSdkSetK1(0), r;
    if (len <= 0 || !data) {
        pspSdkSetK1(k1);
        return -1;
    }
    if (g_mode == PML_MODE_HOSTFS) {
        r = usbAsyncReadWithTimeout(ASYNC_USER, (unsigned char *)data, len, timeout_us);
        if (r < 0) r = 0; /* usbhostfs returns -1 on timeout */
        g_rx_bytes += r;
    } else if (g_mode == PML_MODE_MACLINK) {
        if (g_state != 2) {
            if (timeout_us > 0) sceKernelDelayThread(timeout_us > 100000 ? 100000 : timeout_us);
            r = 0;
        } else {
            sceKernelWaitSema(g_rxsema, 1, NULL);
            r = maclink_read((unsigned char *)data, len, timeout_us);
            sceKernelSignalSema(g_rxsema, 1);
        }
    } else {
        r = -2;
    }
    pspSdkSetK1(k1);
    return r;
}

int pmlInfo(int *out, int n) {
    int k1 = pspSdkSetK1(0);
    int v[4];
    int i;
    v[0] = g_speed;
    v[1] = (int)g_rx_bytes;
    v[2] = (int)g_tx_bytes;
    v[3] = g_last_err;
    for (i = 0; i < n && i < 4; i++) out[i] = v[i];
    pspSdkSetK1(k1);
    return 4;
}

int module_start(SceSize args, void *argp) {
    (void)args; (void)argp;
    g_ev = sceKernelCreateEventFlag("PmlEvent", 0x200, 0, NULL);
    g_txsema = sceKernelCreateSema("PmlTx", 0, 1, 1, NULL);
    g_rxsema = sceKernelCreateSema("PmlRx", 0, 1, 1, NULL);
    return 0;
}

int module_stop(SceSize args, void *argp) {
    (void)args; (void)argp;
    pmlStop();
    if (g_registered) sceUsbbdUnregister(&g_driver);
    if (g_ev >= 0) sceKernelDeleteEventFlag(g_ev);
    if (g_txsema >= 0) sceKernelDeleteSema(g_txsema);
    if (g_rxsema >= 0) sceKernelDeleteSema(g_rxsema);
    return 0;
}
