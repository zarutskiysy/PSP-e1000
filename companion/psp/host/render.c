/* render.c — draws the real app/pet/ui code on the Mac and writes PPM frames, for reviewing the
 * character without an emulator. Usage: render OUT_DIR */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../app.h"
#include "../gfx.h"
#include "../pet.h"
#include "../ui.h"

static uint32_t fb[GFX_STRIDE * GFX_H];
static int emit(void *c, uint8_t t, const void *p, uint32_t n) { (void)c; (void)t; (void)p; (void)n; return 0; }

static void write_ppm(const char *dir, const char *name) {
    char path[512];
    FILE *f;
    int x, y;
    snprintf(path, sizeof path, "%s/%s.ppm", dir, name);
    f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    fprintf(f, "P6\n%d %d\n255\n", GFX_W, GFX_H);
    for (y = 0; y < GFX_H; y++)
        for (x = 0; x < GFX_W; x++) {
            uint32_t c = fb[y * GFX_STRIDE + x];
            unsigned char rgb[3] = {(unsigned char)c, (unsigned char)(c >> 8), (unsigned char)(c >> 16)};
            fwrite(rgb, 1, 3, f);
        }
    fclose(f);
}

typedef struct {
    const char *name;
    uint8_t state;
    const char *status;
    float secs;
    uint8_t mode;
    int overlay; /* 1 approval, 2 menu, 3 notification, 4 diag, 5 chip */
} shot_t;

static const shot_t k_shots[] = {
    {"01_offline", PC_AG_OFFLINE, "", 3.2f, PC_MODE_NONE, 0},
    {"02_sleeping", PC_AG_SLEEPING, "Waiting for a Codex session", 3.2f, PC_MODE_NONE, 0},
    {"03_idle", PC_AG_IDLE, "Idle", 2.0f, PC_MODE_OBSERVE, 0},
    {"04_thinking", PC_AG_THINKING, "Thinking...", 2.0f, PC_MODE_OBSERVE, 0},
    {"05_editing", PC_AG_EDITING, "Editing main.py", 3.4f, PC_MODE_HOOKS, 0},
    {"06_running", PC_AG_RUNNING, "Running: git status --short", 2.0f, PC_MODE_MANAGED, 0},
    {"07_testing", PC_AG_TESTING, "Running tests", 1.5f, PC_MODE_MANAGED, 0},
    {"08_approval", PC_AG_APPROVAL, "Waiting for approval", 2.0f, PC_MODE_MANAGED, 1},
    {"09_success", PC_AG_SUCCESS, "Task complete", 1.2f, PC_MODE_MANAGED, 0},
    {"10_failed", PC_AG_FAILED, "Command failed", 2.0f, PC_MODE_MANAGED, 0},
    {"11_talking", PC_AG_TALKING, "Writing reply", 2.0f, PC_MODE_DEMO, 0},
    {"12_menu", PC_AG_IDLE, "Idle", 2.0f, PC_MODE_MANAGED, 2},
    {"13_notify", PC_AG_APPROVAL, "Waiting for approval", 2.0f, PC_MODE_OBSERVE, 3},
    {"14_diag", PC_AG_WORKING, "Using github: list_pull_requests", 2.0f, PC_MODE_MANAGED, 4},
    {"15_chip", PC_AG_IDLE, "Idle", 2.0f, PC_MODE_MANAGED, 5},
};

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    size_t i;
    gfx_begin(fb);
    for (i = 0; i < sizeof k_shots / sizeof k_shots[0]; i++) {
        const shot_t *s = &k_shots[i];
        static app_t a;
        static pet_t pet;
        ui_view_t v;
        ui_stats_t st;
        uint32_t now = 100000;
        int f, frames = (int)(s->secs * 60.0f), j;
        app_init(&a, emit, NULL);
        pet_init(&pet, 12345u + (uint32_t)i);
        ui_init(&v);
        memset(&st, 0, sizeof st);
        st.fps = 60; st.frame_ms = 9.4f; st.io_name = "usb-maclink"; st.quality = 1; st.rx_frames = 1234; st.tx_frames = 987;
        if (s->state != PC_AG_OFFLINE) {
            app_on_link(&a, 1, now);
            a.agent = s->state;
            a.mode = s->mode;
            a.conn = s->mode ? PC_CONN_ATTACHED : PC_CONN_NONE;
            snprintf(a.activity, sizeof a.activity, "%s", s->status);
            snprintf(a.label, sizeof a.label, "psp_e1000");
            a.sess_count = 1;
            for (j = 0; j < PC_ACT_COUNT; j++) a.actions[j].enabled = j != 4;
            snprintf(a.actions[4].reason, sizeof a.actions[4].reason, "No turn is running");
        }
        if (s->overlay == 1 || s->overlay == 3) {
            a.ap.phase = AP_SHOWING;
            a.ap.id = 42;
            a.ap.armed = 1;
            a.ap.flags = s->overlay == 1 ? PC_AF_ACTIONABLE : 0;
            a.ap.timeout_s = 120;
            a.ap.shown_ms = now;
            a.ap.pending = 1;
            snprintf(a.ap.title, sizeof a.ap.title, "Run command?");
            snprintf(a.ap.detail, sizeof a.ap.detail, s->overlay == 1 ? "npm test" : "rm -rf build && make -j8 all && ./scripts/deploy.sh --target staging --verbose");
        }
        if (s->overlay == 2) { a.menu_open = 1; a.selected = 2; }
        if (s->overlay == 4) a.diag = 1;
        if (s->overlay == 5) { a.chip_until = now + 100000; a.selected = 2; }
        for (f = 0; f < frames; f++) {
            pet_set_state(&pet, app_pet_state(&a));
            pet_update(&pet, 1.0f / 60.0f);
            ui_update(&v, &a, 1.0f / 60.0f);
            now += 16;
            ui_draw(&v, &a, &pet, &st, now);
        }
        write_ppm(dir, s->name);
    }
    return 0;
}
