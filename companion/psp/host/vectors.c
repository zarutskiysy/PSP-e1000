/* vectors.c — drives the real app.c from a line script so Python can cross-check the wire format.
 *   F <type> <hex|-> <now>    feed a payload        -> "F <accepted>"
 *   L <0|1> <now>             link up/down
 *   B <held> <now>            buttons
 *   T <now>                   tick
 *   S                         dump state            -> key=value lines, then "END"
 * Everything the app emits is printed as "TX <type> <hex>". */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../app.h"

static int emit(void *c, uint8_t t, const void *p, uint32_t n) {
    const uint8_t *b = p;
    uint32_t i;
    (void)c;
    printf("TX %u ", t);
    for (i = 0; i < n; i++) printf("%02x", b[i]);
    printf("\n");
    return 0;
}

static uint32_t unhex(const char *s, uint8_t *out, uint32_t cap) {
    uint32_t n = 0;
    if (s[0] == '-') return 0;
    while (s[0] && s[1] && n < cap) {
        unsigned v;
        sscanf(s, "%2x", &v);
        out[n++] = (uint8_t)v;
        s += 2;
    }
    return n;
}

int main(void) {
    static app_t a;
    static char line[4096], hex[4000];
    static uint8_t buf[2000];
    app_init(&a, emit, NULL);
    while (fgets(line, sizeof line, stdin)) {
        unsigned u1, u2;
        if (line[0] == 'F' && sscanf(line + 1, "%u %3999s %u", &u1, hex, &u2) == 3) {
            uint32_t n = unhex(hex, buf, sizeof buf);
            printf("F %d\n", app_on_frame(&a, (uint8_t)u1, buf, n, u2));
        } else if (line[0] == 'L' && sscanf(line + 1, "%u %u", &u1, &u2) == 2) {
            app_on_link(&a, (int)u1, u2);
        } else if (line[0] == 'B' && sscanf(line + 1, "%u %u", &u1, &u2) == 2) {
            app_on_buttons(&a, u1, u2);
        } else if (line[0] == 'T' && sscanf(line + 1, "%u", &u1) == 1) {
            app_tick(&a, u1);
        } else if (line[0] == 'S') {
            int i;
            printf("link=%d\nconn=%d\nmode=%d\ncaps=%d\nindex=%d\ncount=%d\nlabel=%s\nagent=%d\nactivity=%s\n", a.link_up,
                   a.conn, a.mode, a.caps, a.sess_index, a.sess_count, a.label, a.agent, a.activity);
            for (i = 0; i < PC_ACT_COUNT; i++) printf("action%d=%d:%s\n", i, a.actions[i].enabled, a.actions[i].reason);
            printf("ap_phase=%d\nap_id=%u\nap_kind=%d\nap_flags=%d\nap_timeout=%d\nap_pending=%d\nap_title=%s\nap_detail=%s\n",
                   a.ap.phase, a.ap.id, a.ap.kind, a.ap.flags, a.ap.timeout_s, a.ap.pending, a.ap.title, a.ap.detail);
            printf("toast=%s\nanim=%d\npeer_boot=%u\nEND\n", a.toast, a.pending_anim, a.peer_boot_id);
        }
        fflush(stdout);
    }
    return 0;
}
