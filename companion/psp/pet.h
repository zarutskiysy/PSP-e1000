/* pet.h — the character: one visor with two cut-out eyes, in a single colour. Every expression is a
 * pose; the current pose eases toward the state's target, so any state change is a smooth transition.
 * All timing uses real elapsed seconds, so a dropped frame changes smoothness, never speed.
 * Plain C (host-buildable). */
#ifndef PC_PET_H
#define PC_PET_H
#include <stdint.h>

typedef struct {
    float band_w, band_h; /* half size of the visor */
    float eye_w, eye_h;   /* half size of each cut-out; eye_w 0 = no eyes */
    float eye_x;          /* distance of each eye from the centre */
    float look_x, look_y; /* -1..1, moves both eyes along the visor */
    float arc, cross;     /* eyes become ^ ^ or x x when > 0.5 */
    float dim, sag;
} pet_pose_t;

typedef struct {
    pet_pose_t p;
    uint8_t state, anim;
    float t, state_t, anim_t;
    float blink, blink_wait, blink_left;
    int blink_double;
    float look_x, look_y, look_wait;
    float pop, pop_v;     /* squash spring: gives every state change a little kick */
    float fx_dx, fx_dy;   /* one-shot animation offsets */
    uint32_t rng;
} pet_t;

void pet_init(pet_t *pet, uint32_t seed);
void pet_set_state(pet_t *pet, uint8_t state);
void pet_play(pet_t *pet, uint8_t anim);
void pet_update(pet_t *pet, float dt);
/* Draws centred at (cx, cy) at the given scale: the visor in fg, the eyes cut out in bg. */
void pet_draw(pet_t *pet, float cx, float cy, float scale, uint32_t fg, uint32_t bg);
#endif
