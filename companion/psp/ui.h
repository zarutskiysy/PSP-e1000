/* ui.h — composes the frame: background, pet, status line and overlays. Reads app_t, never changes it. */
#ifndef PC_UI_H
#define PC_UI_H
#include "app.h"
#include "pet.h"

typedef struct {
    float menu_k, ap_k;        /* overlay slide-in, 0..1 */
    float pet_x, pet_y, pet_s;
} ui_view_t;

typedef struct {
    float fps, frame_ms;
    uint32_t rx_frames, tx_frames, crc_errors, junk;
    const char *io_name;
    int quality;
} ui_stats_t;

void ui_init(ui_view_t *v);
void ui_update(ui_view_t *v, const app_t *a, float dt);
void ui_draw(const ui_view_t *v, const app_t *a, pet_t *pet, const ui_stats_t *st, uint32_t now_ms);
#endif
