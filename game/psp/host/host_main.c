/* host_main.c — macOS build of the PSP console (same C code as the EBOOT).
 *   --demo                  talk to the in-process demo Mac (pipe io), simulated 60 fps clock
 *   --tcp PORT              listen on 127.0.0.1:PORT and act as the PSP for the Mac game
 *                           (blackwater.py --transport tcp:127.0.0.1:PORT), real-time clock
 *   --bot                   scripted player (press START, ping, solve locks)
 *   --frames N              stop after N frames (default: until WIN/LOSE in tcp mode, 600 in demo)
 *   --shot FILE.ppm         dump the 480x272 screen at the end (or at --shot-frame K)
 *   --press F:BTN[,F:BTN]   scripted presses at frame F (BTN = x,o,sq,tri,start,up,down,left,right)
 * Prints a one-line JSON summary at exit. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>
#include "../../../common/psp/io_posix_tcp.h"
#include "../app.h"
#include "../bot.h"
#include "../view.h"

static uint32_t fbmem[BW_STRIDE * BW_SCREEN_H];

static int write_ppm(const char *path, const uint32_t *px) {
    FILE *f = fopen(path, "wb");
    int x, y;
    if (!f) return -1;
    fprintf(f, "P6\n%d %d\n255\n", BW_SCREEN_W, BW_SCREEN_H);
    for (y = 0; y < BW_SCREEN_H; y++)
        for (x = 0; x < BW_SCREEN_W; x++) {
            uint32_t c = px[y * BW_STRIDE + x];
            unsigned char rgb[3] = {(unsigned char)c, (unsigned char)(c >> 8), (unsigned char)(c >> 16)};
            fwrite(rgb, 1, 3, f);
        }
    fclose(f);
    return 0;
}

static uint16_t parse_btn(const char *s) {
    if (!strcmp(s, "x")) return BW_B_CROSS;
    if (!strcmp(s, "o")) return BW_B_CIRCLE;
    if (!strcmp(s, "sq")) return BW_B_SQUARE;
    if (!strcmp(s, "tri")) return BW_B_TRIANGLE;
    if (!strcmp(s, "start")) return BW_B_START;
    if (!strcmp(s, "up")) return BW_B_UP;
    if (!strcmp(s, "down")) return BW_B_DOWN;
    if (!strcmp(s, "left")) return BW_B_LEFT;
    if (!strcmp(s, "right")) return BW_B_RIGHT;
    return 0;
}

static uint32_t now_real_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint32_t)(tv.tv_sec * 1000u + tv.tv_usec / 1000u);
}

static bw_app_t app;

int main(int argc, char **argv) {
    int demo = 0, port = -1, bot = 0, i, fd = -1;
    long frames = -1, shot_frame = -1, f;
    const char *shot = NULL, *press = NULL;
    uint32_t t0;
    bw_gfx_t g = {fbmem};
    if (argc == 4 && !strcmp(argv[1], "--hackgen")) { /* golden check for the Python mirror */
        uint8_t n, t[BW_HACK_MAX], v[BW_HACK_MAX];
        bw_hack_generate((uint32_t)strtoul(argv[2], NULL, 0), (uint8_t)atoi(argv[3]), &n, t, v);
        for (i = 0; i < n; i++) printf("%d%c", t[i], i + 1 < n ? ' ' : '\n');
        for (i = 0; i < n; i++) printf("%d%c", v[i], i + 1 < n ? ' ' : '\n');
        return 0;
    }
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--demo")) demo = 1;
        else if (!strcmp(argv[i], "--bot")) bot = 1;
        else if (!strcmp(argv[i], "--tcp") && i + 1 < argc) port = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--frames") && i + 1 < argc) frames = atol(argv[++i]);
        else if (!strcmp(argv[i], "--shot") && i + 1 < argc) shot = argv[++i];
        else if (!strcmp(argv[i], "--shot-frame") && i + 1 < argc) shot_frame = atol(argv[++i]);
        else if (!strcmp(argv[i], "--press") && i + 1 < argc) press = argv[++i];
        else { fprintf(stderr, "unknown arg %s\n", argv[i]); return 2; }
    }
    if (port >= 0) {
        fprintf(stderr, "[psp_host] listening on 127.0.0.1:%d\n", port);
        fd = psp_tcp_listen_accept("127.0.0.1", port);
        if (fd < 0) { fprintf(stderr, "listen/accept failed\n"); return 3; }
        bw_app_init(&app, psp_tcp_io(&fd), "TCP");
    } else {
        demo = 1;
        bw_app_init_demo(&app);
    }
    if (frames < 0 && demo) frames = 600;
    t0 = now_real_ms();
    for (f = 0; frames < 0 || f < frames; f++) {
        uint32_t now = demo ? (uint32_t)(f * 1000 / 60) : now_real_ms() - t0;
        uint16_t b = bot ? bw_bot_buttons(&app.con, (uint32_t)f, now, 2500) : 0;
        if (press) { /* "F:BTN,F:BTN" */
            const char *p = press;
            while (*p) {
                long pf = strtol(p, (char **)&p, 10);
                char name[16];
                int k = 0;
                if (*p == ':') p++;
                while (*p && *p != ',' && k < 15) name[k++] = *p++;
                name[k] = 0;
                if (*p == ',') p++;
                if (pf == f) b |= parse_btn(name);
            }
        }
        bw_app_step(&app, now, b, 0, 0);
        if (shot && f == shot_frame) { bw_view_draw(&g, &app.con, app.io_name); write_ppm(shot, fbmem); }
        if (!demo) {
            if (app.io_dead) break;
            if (frames < 0 && app.con.phase == BW_PH_OVER) {
                /* let the last frames flush, then stop */
                usleep(200000);
                bw_app_step(&app, now_real_ms() - t0, 0, 0, 0);
                break;
            }
            usleep(16000);
        }
    }
    bw_view_draw(&g, &app.con, app.io_name);
    if (shot && shot_frame < 0) write_ppm(shot, fbmem);
    printf("{\"phase\": %d, \"outcome\": %d, \"pings\": %d, \"echoes\": %d, \"hacks_ok\": %d, \"hacks_failed\": %d, "
           "\"marks\": %d, \"tx_msgs\": %u, \"rx_msgs\": %u, \"frames\": %ld}\n",
           app.con.phase, app.con.outcome, app.con.pings_sent, app.con.echoes_rx, app.con.hacks_ok,
           app.con.hacks_failed, app.con.marks_sent, app.con.tx_msgs, app.con.rx_msgs, f);
    if (fd >= 0) close(fd);
    return 0;
}
