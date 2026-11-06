/*
 * PSP second screen (feat/second-screen): receives SCR_CHUNKs over the PSP<->Mac link, decodes
 * them with screen/codec/scr_codec.c into a RAM canvas, copies dirty tiles to the 565 framebuffer,
 * draws a stats line, and ACKs every frame (flow control + stats for the Mac).
 *
 * The io (transport) is chosen once at startup in open_io(); everything else is io-agnostic:
 *   USB maclink  common/psp/usb (pspmaclink.prx, vendor bulk)      -- real hardware, fast path
 *   USB hostfs   common/psp/usb (usbhostfs.prx + usbhostfs_pc)      -- real hardware, fallback
 *   mailbox      common/psp/io_mailbox (PPSSPP + tools/ppsspp_bridge.py) -- emulator end-to-end
 *                (picked automatically when psp_is_emulator() and there is no screen.cfg)
 *   replay       stream.bin next to the EBOOT (recorded by `psp_screen.py --transport record:...`)
 * Optional screen.cfg next to the EBOOT with one word (usb|hostfs|mailbox|replay) skips the menu.
 *
 * Controls: SELECT toggles the stats line, HOME exits.
 */
#include <pspctrl.h>
#include <pspdebug.h>
#include <pspdisplay.h>
#include <pspiofilemgr.h>
#include <pspkernel.h>
#include <psppower.h>
#include <pspsdk.h>
#include <stdio.h>
#include <string.h>

#include "../../common/psp/link.h"
#include "../codec/scr_codec.h"
#ifdef WITH_USB
#include "../../common/psp/usb/psp_usb_io.h"
#endif
#include "../../common/psp/io_mailbox.h"

PSP_MODULE_INFO("PSPE1000_SCREEN", PSP_MODULE_USER, 1, 0);
PSP_MAIN_THREAD_ATTR(THREAD_ATTR_USER | THREAD_ATTR_VFPU);
PSP_HEAP_SIZE_KB(-1024);

#define FB_STRIDE 512
#define VRAM_UNCACHED ((uint16_t *)0x44000000)
#define OVERLAY_Y 264 /* last 8-pixel text row */

enum { MODE_NONE = 0, MODE_USB, MODE_HOSTFS, MODE_MAILBOX, MODE_REPLAY };
static const char *mode_name[] = {"none", "usb", "hostfs", "mailbox", "replay"};

static volatile int running = 1;
static char base_dir[256] = "ms0:/PSP/GAME/pspscreen";

static uint16_t canvas[SCR_W * SCR_H] __attribute__((aligned(64)));
static uint8_t rx_payload[SCR_MAX_PAYLOAD + 64] __attribute__((aligned(64)));
static uint8_t rx_chunk[64 * 1024] __attribute__((aligned(64)));
static uint8_t tx_buf[512] __attribute__((aligned(64)));
static uint8_t scratch[SCR_MAX_BODY] __attribute__((aligned(64)));

static int exit_cb(int a, int b, void *c) {
    (void)a; (void)b; (void)c;
    running = 0;
    return 0;
}
static int cb_thread(SceSize args, void *argp) {
    (void)args; (void)argp;
    int cbid = sceKernelCreateCallback("exit", exit_cb, NULL);
    sceKernelRegisterExitCallback(cbid);
    sceKernelSleepThreadCB();
    return 0;
}

/* ---- replay io: plays a recorded byte stream in a loop, writes go nowhere -------------------- */
static SceUID replay_fd = -1;
static int replay_write(void *ctx, const void *buf, int len) { (void)ctx; (void)buf; return len; }
static int replay_read(void *ctx, void *buf, int len, int timeout_us) {
    (void)ctx; (void)timeout_us;
    int r = sceIoRead(replay_fd, buf, len);
    if (r <= 0) { /* EOF: loop (the recording starts with a keyframe) */
        sceIoLseek32(replay_fd, 0, PSP_SEEK_SET);
        r = sceIoRead(replay_fd, buf, len);
    }
    return r;
}

static int open_io(int mode, psp_link_io_t *io, char *err, int errlen) {
    switch (mode) {
    case MODE_REPLAY: {
        char path[300];
        snprintf(path, sizeof path, "%s/stream.bin", base_dir);
        replay_fd = sceIoOpen(path, PSP_O_RDONLY, 0);
        if (replay_fd < 0) { snprintf(err, errlen, "cannot open %s (%08X)", path, replay_fd); return -1; }
        io->write = replay_write; io->read = replay_read; io->ctx = NULL;
        return 0;
    }
#ifdef WITH_USB
    case MODE_USB:
    case MODE_HOSTFS: {
        int r = psp_usb_start(mode == MODE_USB ? PSP_USB_MODE_MACLINK : PSP_USB_MODE_HOSTFS);
        if (r < 0) { snprintf(err, errlen, "psp_usb_start: %08X %s", r, psp_usb_last_error()); return -1; }
        *io = psp_usb_io();
        return 0;
    }
#endif
    case MODE_MAILBOX: {
        static uint8_t mbox_mem[64 + 2 * 65536] __attribute__((aligned(64)));
        static psp_mbox_t mb;
        if (psp_mbox_init(&mb, mbox_mem, sizeof mbox_mem, 65536, 65536) < 0) {
            snprintf(err, errlen, "psp_mbox_init failed");
            return -1;
        }
        *io = psp_mbox_io(&mb);
        return 0;
    }
    default:
        snprintf(err, errlen, "io '%s' not compiled into this build", mode_name[mode]);
        return -1;
    }
}

static int read_cfg(void) {
    char path[300], buf[16] = {0};
    snprintf(path, sizeof path, "%s/screen.cfg", base_dir);
    SceUID fd = sceIoOpen(path, PSP_O_RDONLY, 0);
    if (fd < 0) return MODE_NONE;
    sceIoRead(fd, buf, sizeof buf - 1);
    sceIoClose(fd);
    for (int m = MODE_USB; m <= MODE_REPLAY; m++)
        if (!strncmp(buf, mode_name[m], strlen(mode_name[m]))) return m;
    return MODE_NONE;
}

static int menu(void) {
    SceCtrlData pad;
    unsigned prev = 0xFFFFFFFF;
    pspDebugScreenClear();
    while (running) {
        pspDebugScreenSetXY(0, 0);
        pspDebugScreenPrintf("PSP E1000 second screen\n\nChoose the link to the Mac:\n\n");
        pspDebugScreenPrintf("  CROSS     USB maclink (fast; psp_screen.py --transport usb)%s\n",
#ifdef WITH_USB
                             "");
#else
                             "  [not in build]");
#endif
        pspDebugScreenPrintf("  CIRCLE    USB hostfs  (fallback; usbhostfs_pc + --transport hostfs)%s\n",
#ifdef WITH_USB
                             "");
#else
                             "  [not in build]");
#endif
        pspDebugScreenPrintf("  TRIANGLE  emulator mailbox (PPSSPP + tools/ppsspp_bridge.py)\n");
        pspDebugScreenPrintf("  SQUARE    replay stream.bin from the EBOOT folder\n\n");
        pspDebugScreenPrintf("dir: %s\nHOME exits. SELECT toggles stats while streaming.\n", base_dir);
        sceCtrlPeekBufferPositive(&pad, 1);
        unsigned down = pad.Buttons & ~prev;
        prev = pad.Buttons;
        if (down & PSP_CTRL_CROSS) return MODE_USB;
        if (down & PSP_CTRL_CIRCLE) return MODE_HOSTFS;
        if (down & PSP_CTRL_TRIANGLE) return MODE_MAILBOX;
        if (down & PSP_CTRL_SQUARE) return MODE_REPLAY;
        sceDisplayWaitVblankStart();
    }
    return MODE_NONE;
}

typedef struct {
    uint32_t t_sec, frames_sec, bytes_sec;
    uint32_t fps_x10, kbps;          /* last second */
    uint32_t dec_us, present_us;     /* last frame */
    uint32_t frames_shown, rx_bytes;
    uint32_t probe_bytes, probe_frames, probe_t0, probe_t1;
    int probe_active;
} stats_t;

static psp_link_t *g_link;

static void draw_overlay(const stats_t *s, const scr_decoder_t *d, int mode, int status) {
    pspDebugScreenSetXY(0, OVERLAY_Y / 8);
    pspDebugScreenSetBackColor(0xFF000000);
    pspDebugScreenSetTextColor(status ? 0xFF4040FF : 0xFF40FF40);
    pspDebugScreenPrintf("%2lu.%lufps %2lu.%02luMB/s dec%2lu.%lums %s #%lu e%lu c%lu%s          ",
                         (unsigned long)(s->fps_x10 / 10), (unsigned long)(s->fps_x10 % 10),
                         (unsigned long)(s->kbps / 1000), (unsigned long)(s->kbps % 1000 / 10),
                         (unsigned long)(s->dec_us / 1000), (unsigned long)(s->dec_us % 1000 / 100), mode_name[mode],
                         (unsigned long)s->frames_shown, (unsigned long)d->errors,
                         (unsigned long)(g_link->parser.crc_errors + g_link->parser.oversize_frames),
                         d->need_key ? " KEY?" : "");
}

static void send_ack(psp_link_t *l, const scr_decoder_t *d, const stats_t *s, unsigned buttons) {
    uint8_t p[SCR_ACK_SIZE];
    psp_link_put_u32(p + 0, d->last_frame_id);
    psp_link_put_u32(p + 4, s->dec_us);
    psp_link_put_u32(p + 8, s->present_us);
    psp_link_put_u32(p + 12, s->frames_shown);
    psp_link_put_u32(p + 16, s->rx_bytes);
    psp_link_put_u32(p + 20, buttons);
    psp_link_put_u16(p + 24, (uint16_t)s->fps_x10);
    psp_link_put_u16(p + 26, d->need_key ? SCR_ACKF_NEED_KEY : 0);
    psp_link_put_u32(p + 28, d->errors);
    psp_link_send(l, SCR_T_ACK, 0, p, SCR_ACK_SIZE);
}

int main(int argc, char *argv[]) {
    SceUID th = sceKernelCreateThread("cb", cb_thread, 0x11, 0xFA0, 0, 0);
    if (th >= 0) sceKernelStartThread(th, 0, 0);
    if (argc > 0 && argv[0]) { /* argv[0] = .../EBOOT.PBP -> its directory */
        strncpy(base_dir, argv[0], sizeof base_dir - 1);
        char *slash = strrchr(base_dir, '/');
        if (slash) *slash = 0;
    }
    pspDebugScreenInitEx(VRAM_UNCACHED, PSP_DISPLAY_PIXEL_FORMAT_565, 1);
    sceCtrlSetSamplingCycle(0);
    sceCtrlSetSamplingMode(PSP_CTRL_MODE_DIGITAL);

    int mode = read_cfg();
    if (mode == MODE_NONE && psp_is_emulator()) mode = MODE_MAILBOX; /* PPSSPP: no USB, use the bridge */
    if (mode == MODE_NONE) mode = menu();
    if (!running) { sceKernelExitGame(); return 0; }

    psp_link_io_t io;
    char err[400];
    pspDebugScreenClear();
    pspDebugScreenPrintf("PSP E1000 second screen -- io: %s\n\n", mode_name[mode]);
    if (open_io(mode, &io, err, sizeof err) < 0) {
        pspDebugScreenPrintf("ERROR: %s\n\nHOME to exit.\n", err);
        while (running) sceDisplayWaitVblankStart();
        sceKernelExitGame();
        return 0;
    }
    pspDebugScreenPrintf("waiting for the Mac: python screen/mac/psp_screen.py --transport %s\n",
                         mode == MODE_USB ? "usb" : mode == MODE_HOSTFS ? "hostfs" : "mock");

    static psp_link_t link;
    static scr_decoder_t dec;
    stats_t st;
    memset(&st, 0, sizeof st);
    psp_link_init(&link, io, rx_payload, sizeof rx_payload, tx_buf, sizeof tx_buf, rx_chunk, sizeof rx_chunk);
    g_link = &link;
    link.app = 2; /* screen */
    link.name = "psp-screen";
    scr_dec_init(&dec, canvas, SCR_W);

    int overlay = 1, first = 1, io_err = 0;
    unsigned prev_buttons = 0, buttons = 0;
    uint32_t last_overlay = 0, last_frame_t = 0, last_tick = 0;
    st.t_sec = sceKernelGetSystemTimeLow();

    while (running) {
        psp_link_frame_t f;
        int r = psp_link_poll(&link, mode == MODE_REPLAY ? 0 : 2000, &f);
        uint32_t now = sceKernelGetSystemTimeLow();
        if (r < 0) {
            if (!io_err) {
                pspDebugScreenSetXY(0, 4);
                pspDebugScreenPrintf("io error %08X -- reconnect the Mac side\n", r);
            }
            io_err = 1;
            sceKernelDelayThread(10000);
        } else if (r == 1) {
            uint32_t nbytes = f.len + PSP_LINK_OVERHEAD;
            st.rx_bytes += nbytes;
            st.bytes_sec += nbytes;
            if (f.type == SCR_T_CHUNK) {
                uint32_t t0 = sceKernelGetSystemTimeLow();
                int dr = scr_dec_chunk(&dec, f.payload, f.len, scratch, sizeof scratch);
                st.dec_us += sceKernelGetSystemTimeLow() - t0;
                if (dr == SCR_DEC_FRAME_DONE || (dr < 0 && f.len >= SCR_CHUNK_HDR && (f.payload[9] & SCR_CF_LAST))) {
                    if (mode == MODE_REPLAY) { /* pace the recording at ~30 fps */
                        int32_t wait = 33333 - (int32_t)(sceKernelGetSystemTimeLow() - last_frame_t);
                        if (wait > 0) sceKernelDelayThread(wait);
                    }
                    last_frame_t = sceKernelGetSystemTimeLow();
                    uint32_t t1 = last_frame_t;
                    if (overlay) scr_mark_rows_dirty(&dec, OVERLAY_Y, SCR_H); /* restore under the old stats */
                    scr_present(&dec, VRAM_UNCACHED, FB_STRIDE, first);
                    first = 0;
                    st.frames_shown++;
                    st.frames_sec++;
                    if (overlay) draw_overlay(&st, &dec, mode, dec.need_key);
                    st.present_us = sceKernelGetSystemTimeLow() - t1;
                    send_ack(&link, &dec, &st, buttons);
                    st.dec_us = 0;
                    last_overlay = now;
                }
            } else if (f.type == SCR_T_PROBE_RESET) {
                st.probe_bytes = st.probe_frames = 0;
                st.probe_active = 0;
            } else if (f.type == SCR_T_PROBE_DATA) {
                if (!st.probe_active) st.probe_t0 = now, st.probe_active = 1;
                st.probe_t1 = now;
                st.probe_bytes += nbytes;
                st.probe_frames++;
            } else if (f.type == SCR_T_PROBE_END && f.len >= 4) {
                uint8_t p[SCR_PROBE_RESULT_SIZE];
                memcpy(p, f.payload, 4);
                psp_link_put_u32(p + 4, st.probe_bytes);
                psp_link_put_u32(p + 8, st.probe_frames);
                psp_link_put_u32(p + 12, st.probe_t1 - st.probe_t0);
                psp_link_put_u32(p + 16, link.parser.crc_errors);
                psp_link_send(&link, SCR_T_PROBE_RESULT, 0, p, sizeof p);
                pspDebugScreenSetXY(0, 6);
                pspDebugScreenPrintf("probe: %lu bytes in %lu us = %lu KB/s     \n", (unsigned long)st.probe_bytes,
                                     (unsigned long)(st.probe_t1 - st.probe_t0),
                                     (unsigned long)(st.probe_t1 != st.probe_t0
                                                         ? (uint64_t)st.probe_bytes * 1000 / (st.probe_t1 - st.probe_t0)
                                                         : 0));
                st.probe_active = 0;
            } else if (f.type == PSP_LINK_T_HELLO) {
                io_err = 0;
                if (first) {
                    pspDebugScreenSetXY(0, 3);
                    pspDebugScreenPrintf("Mac connected (peer max_payload %lu)\n",
                                         (unsigned long)link.peer.max_payload);
                }
            }
        }
        if (now - st.t_sec >= 1000000) {
            uint32_t dt = now - st.t_sec;
            st.fps_x10 = (uint32_t)((uint64_t)st.frames_sec * 10000000ull / dt);
            st.kbps = (uint32_t)((uint64_t)st.bytes_sec * 1000ull / dt); /* bytes/ms = KB/s */
            st.frames_sec = st.bytes_sec = 0;
            st.t_sec = now;
        }
        if (now - last_tick > 1000000) { /* keep the backlight/auto-sleep away, poll buttons */
            scePowerTick(0);
            last_tick = now;
        }
        SceCtrlData pad;
        sceCtrlPeekBufferPositive(&pad, 1);
        buttons = pad.Buttons;
        if ((buttons & ~prev_buttons) & PSP_CTRL_SELECT) {
            overlay = !overlay;
            scr_mark_rows_dirty(&dec, OVERLAY_Y, SCR_H);
            scr_present(&dec, VRAM_UNCACHED, FB_STRIDE, 0);
        }
        prev_buttons = buttons;
#ifdef WITH_USB
        if (first && (mode == MODE_USB || mode == MODE_HOSTFS) && now - last_overlay > 500000) {
            int info[4] = {0, 0, 0, 0};
            static const char *stn[] = {"off", "waiting for host", "connected"};
            int ust = psp_usb_state();
            psp_usb_info(info);
            pspDebugScreenSetXY(0, 8);
            pspDebugScreenPrintf("USB: %s, speed %s, rx %d B, tx %d B, last err %08X   \n",
                                 stn[ust >= 0 && ust <= 2 ? ust : 0],
                                 info[0] == 2 ? "HIGH (480M)" : info[0] == 1 ? "FULL (12M!)" : "?", info[1], info[2],
                                 info[3]);
            last_overlay = now;
        }
#endif
        if (overlay && !first && now - last_overlay > 500000) { /* refresh stats when idle */
            scr_mark_rows_dirty(&dec, OVERLAY_Y, SCR_H);
            scr_present(&dec, VRAM_UNCACHED, FB_STRIDE, 0);
            draw_overlay(&st, &dec, mode, dec.need_key);
            last_overlay = now;
        }
    }
#ifdef WITH_USB
    if (mode == MODE_USB || mode == MODE_HOSTFS) psp_usb_stop();
#endif
    sceKernelExitGame();
    return 0;
}
