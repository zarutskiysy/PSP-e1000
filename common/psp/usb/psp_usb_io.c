/* psp_usb_io.c — user-mode side of the real USB transport (see psp_usb_io.h). PSP only.
 * Loads usbhostfs.prx + pspmaclink.prx from the EBOOT's directory and calls pspmaclink's syscalls.
 * UNTESTED ON HARDWARE as of 2026-11-07 (built without a PSP); see HARDWARE_TEST.md on each branch. */
#include <kubridge.h>
#include <pspkerror.h>
#include <pspkernel.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "prx/pspmaclink.h"
#include "psp_usb_io.h"

static char g_err[128] = "";
static int g_started = 0;

static SceUID load_start(const char *name) {
    char path[256];
    SceUID mod;
    int status = 0, r;
    if (!getcwd(path, sizeof path - 32)) strcpy(path, "ms0:/PSP/GAME");
    strcat(path, "/");
    strcat(path, name);
    mod = sceKernelLoadModule(path, 0, NULL);
    if (mod < 0 && mod != (SceUID)SCE_KERNEL_ERROR_EXCLUSIVE_LOAD) {
        SceUID m2 = kuKernelLoadModule(path, 0, NULL); /* CFW kubridge fallback (PRO / ME / ARK) */
        if (m2 >= 0 || m2 == (SceUID)SCE_KERNEL_ERROR_EXCLUSIVE_LOAD) mod = m2;
    }
    if (mod == (SceUID)SCE_KERNEL_ERROR_EXCLUSIVE_LOAD) return 0; /* already resident */
    if (mod < 0) {
        snprintf(g_err, sizeof g_err, "load %s: %08X", path, (unsigned)mod);
        return mod;
    }
    r = sceKernelStartModule(mod, 0, NULL, &status, NULL);
    if (r < 0) {
        snprintf(g_err, sizeof g_err, "start %s: %08X", name, (unsigned)r);
        return r;
    }
    return mod;
}

int psp_usb_start(int mode) {
    int r;
    if (g_started) return 0;
    /* pspmaclink.prx imports usbhostfs.prx's kernel library, so usbhostfs always loads first. */
    if ((r = load_start("usbhostfs.prx")) < 0) return r;
    if ((r = load_start("pspmaclink.prx")) < 0) return r;
    r = pmlStart(mode == PSP_USB_MODE_MACLINK ? PML_MODE_MACLINK : PML_MODE_HOSTFS);
    if (r < 0) {
        snprintf(g_err, sizeof g_err, "pmlStart(%d): %08X", mode, (unsigned)r);
        return r;
    }
    g_started = 1;
    strcpy(g_err, "ok");
    return 0;
}

void psp_usb_stop(void) {
    if (g_started) pmlStop();
    g_started = 0;
}

int psp_usb_state(void) { return g_started ? pmlState() : PSP_USB_STATE_OFF; }

const char *psp_usb_last_error(void) { return g_err; }

int psp_usb_info(int out[4]) {
    if (!g_started) return -1;
    pmlInfo(out, 4);
    return 0;
}

static int usb_write(void *ctx, const void *buf, int len) {
    int r;
    (void)ctx;
    r = pmlWrite(buf, len);
    /* Not connected yet: drop silently. The Mac starts every session with HELLO, so nothing that
     * matters is lost; the link layer must not die while the cable is out. */
    if (r == -2) return len;
    return r;
}

static int usb_read(void *ctx, void *buf, int len, int timeout_us) {
    (void)ctx;
    return pmlRead(buf, len, timeout_us);
}

psp_link_io_t psp_usb_io(void) {
    psp_link_io_t io;
    io.write = usb_write;
    io.read = usb_read;
    io.ctx = NULL;
    return io;
}
