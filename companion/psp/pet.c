#include "pet.h"

#include <math.h>
#include <string.h>

#include "../proto_companion.h"
#include "gfx.h"

#define PI 3.1415927f
#define EYE_TRAVEL_X 52.0f
#define EYE_TRAVEL_Y 13.0f

/* The visor closes to a line with no Mac and to a slit when asleep; everything else is the eyes.
 *                    band_w band_h eye_w eye_h eye_x look_x look_y arc cross dim sag */
static const pet_pose_t k_pose[PC_AG_COUNT] = {
    [PC_AG_OFFLINE]  = {170, 4,  0,  0,    84, 0,     0,     0, 0, .38f, 0},
    [PC_AG_SLEEPING] = {196, 22, 20, 2.5f, 84, 0,     0,     0, 0, .62f, 0},
    [PC_AG_IDLE]     = {196, 56, 17, 33,   84, 0,     0,     0, 0, 1,    0},
    [PC_AG_THINKING] = {196, 56, 17, 27,   84, .7f,   -.6f,  0, 0, 1,    0},
    [PC_AG_EDITING]  = {196, 56, 24, 9,    84, -.3f,  .6f,   0, 0, 1,    0},
    [PC_AG_RUNNING]  = {196, 56, 17, 30,   84, 0,     0,     0, 0, 1,    0},
    [PC_AG_TESTING]  = {196, 56, 17, 30,   84, 0,     0,     0, 0, 1,    0},
    [PC_AG_APPROVAL] = {196, 56, 23, 44,   84, 0,     0,     0, 0, 1,    0},
    [PC_AG_SUCCESS]  = {196, 56, 17, 2,    84, 0,     0,     1, 0, 1,    0},
    [PC_AG_FAILED]   = {196, 48, 17, 2,    84, 0,     0,     0, 1, .85f, 8},
    [PC_AG_TALKING]  = {196, 56, 17, 30,   84, 0,     0,     0, 0, 1,    0},
    [PC_AG_WORKING]  = {196, 56, 18, 26,   84, 0,     0,     0, 0, 1,    0},
};

static uint32_t rnd(pet_t *p) {
    uint32_t x = p->rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    p->rng = x;
    return x;
}
static float rndf(pet_t *p, float a, float b) { return a + (b - a) * (float)(rnd(p) & 0xFFFF) / 65535.0f; }
static float clampf(float v, float a, float b) { return v < a ? a : v > b ? b : v; }
static int is_asleep(uint8_t s) { return s == PC_AG_OFFLINE || s == PC_AG_SLEEPING; }

void pet_init(pet_t *pet, uint32_t seed) {
    memset(pet, 0, sizeof *pet);
    pet->rng = seed | 1u;
    pet->state = PC_AG_OFFLINE;
    pet->p = k_pose[PC_AG_OFFLINE];
    pet->blink_wait = 2.0f;
}

void pet_set_state(pet_t *pet, uint8_t state) {
    if (state >= PC_AG_COUNT || state == pet->state) return;
    pet->state = state;
    pet->state_t = 0.0f;
    pet->look_wait = 0.0f;
    pet->pop_v += 2.0f;
}

void pet_play(pet_t *pet, uint8_t anim) {
    pet->anim = anim;
    pet->anim_t = 0.0f;
}

static void update_look(pet_t *pet, float dt) {
    const pet_pose_t *k = &k_pose[pet->state];
    pet->look_wait -= dt;
    switch (pet->state) {
    case PC_AG_RUNNING: /* sweeps along the visor */
        pet->look_x = sinf(pet->t * 2.6f);
        pet->look_y = 0.0f;
        return;
    case PC_AG_TESTING: { /* steps across it, one test at a time */
        int n = (int)(pet->t * 3.0f) % 5;
        pet->look_x = -1.0f + (float)n * .5f;
        pet->look_y = 0.0f;
        return;
    }
    case PC_AG_WORKING:
        pet->look_x = sinf(pet->t * .9f) * .4f;
        pet->look_y = 0.0f;
        return;
    default:
        break;
    }
    if (pet->look_wait > 0.0f) return;
    switch (pet->state) {
    case PC_AG_IDLE:
        pet->look_x = rndf(pet, -.6f, .6f);
        pet->look_y = rndf(pet, -.4f, .4f);
        pet->look_wait = rndf(pet, 1.1f, 3.8f);
        break;
    case PC_AG_THINKING:
        pet->look_x = k->look_x + rndf(pet, -.25f, .25f);
        pet->look_y = k->look_y + rndf(pet, -.2f, .2f);
        pet->look_wait = rndf(pet, .5f, 1.3f);
        break;
    case PC_AG_EDITING: /* small twitches, like keystrokes */
        pet->look_x = k->look_x + rndf(pet, -.07f, .07f);
        pet->look_y = k->look_y + rndf(pet, -.1f, .1f);
        pet->look_wait = .08f;
        break;
    default:
        pet->look_x = k->look_x;
        pet->look_y = k->look_y;
        pet->look_wait = 1.0f;
        break;
    }
}

static void update_blink(pet_t *pet, float dt) {
    const float d = .17f;
    if (pet->blink_left > 0.0f) {
        pet->blink_left -= dt;
        pet->blink = sinf(clampf(1.0f - pet->blink_left / d, 0, 1) * PI);
        if (pet->blink_left <= 0.0f) {
            pet->blink = 0.0f;
            if (pet->blink_double) {
                pet->blink_double = 0;
                pet->blink_wait = .09f;
            }
        }
    } else {
        pet->blink_wait -= dt;
        if (pet->blink_wait <= 0.0f) {
            pet->blink_left = d;
            pet->blink_double = (rnd(pet) % 5) == 0;
            pet->blink_wait = rndf(pet, 1.8f, 5.2f);
        }
    }
}

static void update_anim(pet_t *pet, float dt) {
    float t;
    pet->fx_dx = pet->fx_dy = 0.0f;
    if (pet->state == PC_AG_APPROVAL) pet->fx_dx = sinf(pet->t * 46.0f) * (pet->state_t < .7f ? 3.0f : .8f);
    if (pet->state == PC_AG_SUCCESS && pet->state_t < 1.7f) pet->fx_dy = -fabsf(sinf(pet->state_t * 7.4f)) * 16.0f;
    if (pet->anim == PC_ANIM_NONE) return;
    pet->anim_t += dt;
    t = pet->anim_t;
    switch (pet->anim) {
    case PC_ANIM_WAKE:
        if (t < .6f) pet->fx_dy = -14.0f * sinf(t / .6f * PI);
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_CELEBRATE:
    case PC_ANIM_BOUNCE:
        if (t < .36f) pet->fx_dy += -12.0f * sinf(t / .36f * PI);
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_FAIL:
        if (t < .55f) pet->fx_dx = sinf(t * 60.0f) * 6.0f * (1.0f - t / .55f);
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_ALLOWED:
        if (t < .6f) pet->fx_dy = 7.0f * sinf(t / .6f * 2.0f * PI);
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_DENIED:
        if (t < .6f) pet->fx_dx = 12.0f * sinf(t / .6f * 4.0f * PI) * (1.0f - t / .6f);
        else pet->anim = PC_ANIM_NONE;
        break;
    default:
        pet->anim = PC_ANIM_NONE;
        break;
    }
}

void pet_update(pet_t *pet, float dt) {
    const pet_pose_t *k = &k_pose[pet->state];
    pet_pose_t *p = &pet->p;
    float a, gaze, eye_h = k->eye_h;

    if (dt > .1f) dt = .1f;
    a = 1.0f - expf(-dt * 12.0f);
    gaze = 1.0f - expf(-dt * 16.0f);
    pet->t += dt;
    pet->state_t += dt;

    update_look(pet, dt);
    update_blink(pet, dt);

    /* no mouth, so speech is the eyes pulsing */
    if (pet->state == PC_AG_TALKING) eye_h = 14.0f + 18.0f * fabsf(sinf(pet->t * 9.0f) * sinf(pet->t * 2.7f));

#define EASE(f) p->f += (k->f - p->f) * a
    EASE(band_w); EASE(band_h); EASE(eye_w); EASE(eye_x); EASE(arc); EASE(cross); EASE(dim); EASE(sag);
#undef EASE
    p->eye_h += (eye_h - p->eye_h) * a;
    p->look_x += (pet->look_x - p->look_x) * gaze;
    p->look_y += (pet->look_y - p->look_y) * gaze;

    {
        float acc = -180.0f * pet->pop - 13.0f * pet->pop_v;
        pet->pop_v += acc * dt;
        pet->pop += pet->pop_v * dt * .12f;
    }
    update_anim(pet, dt);
}

static void draw_arch(float cx, float cy, float hw, float rise, float w, uint32_t c) {
    enum { N = 15 };
    vec2_t pts[N];
    int i;
    for (i = 0; i < N; i++) {
        float u = (float)i / (N - 1) * 2.0f - 1.0f;
        pts[i].x = cx + u * hw;
        pts[i].y = cy - rise * (1.0f - u * u);
    }
    gfx_stroke(pts, N, w, c);
}

void pet_draw(pet_t *pet, float cx, float cy, float s, uint32_t fg, uint32_t bg) {
    const pet_pose_t *p = &pet->p;
    float breath = sinf(pet->t * (is_asleep(pet->state) ? 1.5f : 2.5f));
    float x = cx + pet->fx_dx * s;
    float y = cy + (pet->fx_dy + p->sag + (is_asleep(pet->state) ? 0.0f : sinf(pet->t * 1.7f) * 1.6f)) * s;
    float bw = p->band_w * (1.0f - pet->pop * .35f) + (pet->state == PC_AG_OFFLINE ? breath * 9.0f : 0.0f);
    float bh = p->band_h * (1.0f + pet->pop + breath * .012f);
    uint32_t band = (fg & 0xFFFFFFu) | ((uint32_t)(clampf(p->dim, 0, 1) * 255.0f) << 24);
    float side;

    gfx_rrect(x - bw * s, y - bh * s, 2.0f * bw * s, 2.0f * bh * s, bh * s, band);

    for (side = -1.0f; side <= 1.0f; side += 2.0f) {
        float ex = x + (side * p->eye_x + p->look_x * EYE_TRAVEL_X) * s;
        float ey = y + p->look_y * EYE_TRAVEL_Y * s;
        if (p->arc > .5f) {
            float g = (p->arc - .5f) * 2.0f;
            draw_arch(x + side * p->eye_x * s, y + 14.0f * s, 30.0f * g * s, 34.0f * g * s, 13.0f * s, bg);
        } else if (p->cross > .5f) {
            float g = (p->cross - .5f) * 2.0f * 18.0f * s, c0 = x + side * p->eye_x * s;
            gfx_capsule_add(c0 - g, y - g, c0 + g, y + g, 6.0f * s);
            gfx_capsule_add(c0 - g, y + g, c0 + g, y - g, 6.0f * s);
            gfx_path_fill(bg);
        } else if (p->eye_w > 1.0f) {
            float eh = p->eye_h * (1.0f - pet->blink), ew = p->eye_w;
            if (eh < 2.5f) eh = 2.5f;
            gfx_rrect(ex - ew * s, ey - eh * s, 2.0f * ew * s, 2.0f * eh * s, (ew < eh ? ew : eh) * .9f * s, bg);
        }
    }

    if (pet->state == PC_AG_SLEEPING && s > .9f) {
        int i;
        for (i = 0; i < 2; i++) {
            float ph = fmodf(pet->t * .3f + (float)i * .5f, 1.0f);
            gfx_text(gfx_font_body, (int)(x + (150.0f + ph * 24.0f) * s), (int)(y - (46.0f + ph * 46.0f) * s), "z",
                     (fg & 0xFFFFFFu) | ((uint32_t)(190.0f * sinf(ph * PI)) << 24));
        }
    }
}
