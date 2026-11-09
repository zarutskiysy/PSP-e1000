/* pet.h — the procedural character. Every expression is a pose; the current pose eases toward the
 * state's target, so any state change is a smooth transition. All timing uses real elapsed seconds,
 * so a dropped frame changes smoothness, never speed. Plain C (host-buildable). */
#ifndef PC_PET_H
#define PC_PET_H
#include <stdint.h>

#define PET_MAX_PARTICLES 56

typedef struct {
    float eye_open, eye_w, eye_h;
    float look_x, look_y;
    float brow;        /* + focused (inner lid low), - worried (inner lid high) */
    float mouth_curve; /* + smile, - frown */
    float mouth_open, mouth_w;
    float squash, tilt;
    float arm_l, arm_r; /* -1 down .. +1 up */
    float happy, closed; /* eyes become ^ ^ / u u arcs when > 0.5 */
    float blush, dim;
    float r, g, b; /* accent colour, 0..1 */
} pet_pose_t;

typedef struct {
    float x, y, vx, vy, life, max, size, rot, vr;
    uint32_t color;
    uint8_t type;
} pet_particle_t;

typedef struct {
    pet_pose_t p;
    uint8_t state, anim;
    float t, state_t, anim_t;
    float blink, blink_wait, blink_left;
    int blink_double;
    float look_x, look_y, look_wait;
    float sq, sq_v;           /* squash spring: gives every state change a little pop */
    float ant, ant_v;         /* antenna lag */
    float fx_dy, fx_tilt, fx_shake, fx_sq; /* one-shot animation offsets */
    float emit;
    uint32_t rng;
    int quality; /* 0 = drop the outer halo layers when the CPU falls behind */
    pet_particle_t parts[PET_MAX_PARTICLES];
} pet_t;

void pet_init(pet_t *pet, uint32_t seed);
void pet_set_state(pet_t *pet, uint8_t state);
void pet_play(pet_t *pet, uint8_t anim);
void pet_update(pet_t *pet, float dt);
/* Draws centred at (cx, cy) at the given scale. */
void pet_draw(pet_t *pet, float cx, float cy, float scale);
/* Accent colour of the current pose, as 0xAABBGGRR with the given alpha. */
uint32_t pet_accent(const pet_t *pet, int alpha);
#endif
