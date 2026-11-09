#include "pet.h"

#include <math.h>
#include <string.h>

#include "../proto_companion.h"
#include "gfx.h"

#define PI 3.1415927f
#define TAU 6.2831853f

enum { P_Z, P_CONFETTI, P_SPARK, P_DROP, P_RAIN };

/*                              open  w    h    lx    ly   brow  curve mopen mw   sq    tilt  armL armR happy closed blush dim   r     g     b */
static const pet_pose_t k_pose[PC_AG_COUNT] = {
    [PC_AG_OFFLINE]  = {0.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.05f, 0.0f, 0.7f, 0.07f, -.05f, -.3f, -.3f, 0, 1, .15f, .50f, .36f, .40f, .55f},
    [PC_AG_SLEEPING] = {0.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.10f, 0.0f, 0.7f, 0.06f, -.05f, -.3f, -.3f, 0, 1, .30f, .68f, .30f, .36f, .85f},
    [PC_AG_IDLE]     = {1.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.40f, 0.0f, 1.0f, 0.00f, 0.00f, -.2f, -.2f, 0, 0, .55f, 1.0f, .30f, .85f, .75f},
    [PC_AG_THINKING] = {.92f, 1.0f, 1.0f, .55f, -.70f, .12f, 0.02f, 0.0f, 0.5f, 0.00f, 0.10f, -.2f, 0.5f, 0, 0, .40f, 1.0f, .62f, .45f, 1.0f},
    [PC_AG_EDITING]  = {.80f, 1.0f, .95f, .75f, .15f, .55f, 0.15f, 0.0f, 0.6f, 0.02f, 0.05f, 0.1f, 0.6f, 0, 0, .35f, 1.0f, .30f, .62f, 1.0f},
    [PC_AG_RUNNING]  = {1.0f, 1.0f, 1.0f, .30f, 0.00f, .20f, 0.05f, 0.0f, 0.6f, 0.00f, 0.00f, 0.0f, 0.0f, 0, 0, .35f, 1.0f, 1.0f, .72f, .20f},
    [PC_AG_TESTING]  = {1.05f, 1.0f, 1.05f, .30f, -.1f, .05f, -.05f, .15f, 0.5f, -.01f, 0.00f, 0.3f, 0.3f, 0, 0, .35f, 1.0f, 1.0f, .85f, .30f},
    [PC_AG_APPROVAL] = {1.25f, 1.1f, 1.28f, 0.0f, 0.0f, -.75f, -.30f, .38f, 0.6f, -.07f, 0.00f, 0.9f, 0.9f, 0, 0, .15f, 1.0f, 1.0f, .55f, .15f},
    [PC_AG_SUCCESS]  = {0.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.00f, .55f, 1.2f, 0.00f, 0.00f, 1.0f, 1.0f, 1, 0, 1.0f, 1.0f, .35f, .95f, .50f},
    [PC_AG_FAILED]   = {.72f, 1.0f, .90f, 0.0f, .55f, -.85f, -.85f, .04f, 0.8f, 0.08f, -.07f, -.8f, -.8f, 0, 0, .10f, .86f, 1.0f, .30f, .30f},
    [PC_AG_TALKING]  = {1.0f, 1.0f, 1.0f, -.2f, 0.00f, 0.0f, 0.35f, .25f, 0.8f, 0.00f, 0.03f, 0.1f, 0.2f, 0, 0, .55f, 1.0f, .40f, .85f, 1.0f},
    [PC_AG_WORKING]  = {.95f, 1.0f, 1.0f, .40f, 0.05f, .30f, 0.08f, 0.0f, 0.6f, 0.00f, 0.03f, 0.2f, 0.3f, 0, 0, .35f, 1.0f, .36f, .72f, .95f},
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
static uint32_t rgb_a(float r, float g, float b, int a) {
    return GFX_RGBA((int)(clampf(r, 0, 1) * 255), (int)(clampf(g, 0, 1) * 255), (int)(clampf(b, 0, 1) * 255), a);
}

uint32_t pet_accent(const pet_t *pet, int alpha) { return rgb_a(pet->p.r, pet->p.g, pet->p.b, alpha); }

void pet_init(pet_t *pet, uint32_t seed) {
    memset(pet, 0, sizeof *pet);
    pet->rng = seed | 1u;
    pet->state = PC_AG_OFFLINE;
    pet->p = k_pose[PC_AG_OFFLINE];
    pet->blink_wait = 2.0f;
    pet->quality = 1;
}

void pet_set_state(pet_t *pet, uint8_t state) {
    if (state >= PC_AG_COUNT || state == pet->state) return;
    pet->state = state;
    pet->state_t = 0.0f;
    pet->look_wait = 0.0f;
    pet->sq_v += 2.4f; /* the pop */
}

void pet_play(pet_t *pet, uint8_t anim) {
    pet->anim = anim;
    pet->anim_t = 0.0f;
}

static pet_particle_t *spawn(pet_t *pet) {
    int i;
    for (i = 0; i < PET_MAX_PARTICLES; i++)
        if (pet->parts[i].life <= 0.0f) return &pet->parts[i];
    return NULL;
}

static void emit_state_particles(pet_t *pet, float dt) {
    float rate = 0.0f;
    pet_particle_t *q;
    switch (pet->state) {
    case PC_AG_OFFLINE:
    case PC_AG_SLEEPING: rate = 0.7f; break;
    case PC_AG_SUCCESS: rate = pet->state_t < 1.6f ? 38.0f : 4.0f; break;
    case PC_AG_APPROVAL: rate = 1.3f; break;
    case PC_AG_FAILED: rate = 9.0f; break;
    default: break;
    }
    pet->emit += rate * dt;
    while (pet->emit >= 1.0f) {
        pet->emit -= 1.0f;
        q = spawn(pet);
        if (!q) break;
        memset(q, 0, sizeof *q);
        switch (pet->state) {
        case PC_AG_OFFLINE:
        case PC_AG_SLEEPING:
            q->type = P_Z;
            q->x = 54; q->y = -56; q->vx = rndf(pet, 7, 15); q->vy = -19; q->max = 2.8f; q->size = rndf(pet, .8f, 1.2f);
            break;
        case PC_AG_SUCCESS: {
            static const uint32_t c[5] = {GFX_RGB(255, 96, 120), GFX_RGB(255, 208, 72), GFX_RGB(96, 232, 150), GFX_RGB(96, 176, 255), GFX_RGB(208, 128, 255)};
            q->type = P_CONFETTI;
            q->x = rndf(pet, -36, 36); q->y = -70; q->vx = rndf(pet, -130, 130); q->vy = rndf(pet, -230, -110);
            q->max = rndf(pet, 1.1f, 1.8f); q->size = rndf(pet, 3, 5.5f); q->vr = rndf(pet, -9, 9); q->color = c[rnd(pet) % 5];
            break;
        }
        case PC_AG_APPROVAL:
            q->type = P_DROP;
            q->x = 58; q->y = -40; q->vx = 16; q->vy = -18; q->max = .95f; q->size = 5;
            break;
        case PC_AG_FAILED:
            q->type = P_RAIN;
            q->x = rndf(pet, -30, 30); q->y = -92; q->vx = -3; q->vy = 125; q->max = .36f; q->size = 1;
            break;
        default: break;
        }
        q->life = q->max;
    }
}

static void update_look(pet_t *pet, float dt) {
    const pet_pose_t *k = &k_pose[pet->state];
    pet->look_wait -= dt;
    if (pet->look_wait <= 0.0f) {
        switch (pet->state) {
        case PC_AG_IDLE:
            pet->look_x = rndf(pet, -.7f, .7f); pet->look_y = rndf(pet, -.4f, .4f); pet->look_wait = rndf(pet, 1.1f, 3.8f);
            break;
        case PC_AG_RUNNING:
        case PC_AG_TESTING:
            pet->look_x = pet->look_x > 0 ? -.7f : .8f; pet->look_y = k->look_y; pet->look_wait = .55f;
            break;
        case PC_AG_THINKING:
            pet->look_x = k->look_x + rndf(pet, -.3f, .3f); pet->look_y = k->look_y + rndf(pet, -.15f, .15f); pet->look_wait = rndf(pet, .5f, 1.3f);
            break;
        default:
            pet->look_x = k->look_x; pet->look_y = k->look_y; pet->look_wait = 1.0f;
            break;
        }
    }
}

static void update_blink(pet_t *pet, float dt) {
    if (pet->blink_left > 0.0f) {
        float d = .17f, x;
        pet->blink_left -= dt;
        x = clampf(1.0f - pet->blink_left / d, 0, 1);
        pet->blink = sinf(x * PI);
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
            pet->blink_left = .17f;
            pet->blink_double = (rnd(pet) % 5) == 0;
            pet->blink_wait = rndf(pet, 1.8f, 5.2f);
        }
    }
}

static void update_anim(pet_t *pet, float dt) {
    float t;
    pet->fx_dy = pet->fx_tilt = pet->fx_shake = pet->fx_sq = 0.0f;
    if (pet->state == PC_AG_APPROVAL) pet->fx_shake = sinf(pet->t * 46.0f) * (pet->state_t < .8f ? 2.6f : .9f);
    if (pet->state == PC_AG_SUCCESS) {
        float h = fabsf(sinf(pet->t * 7.5f));
        pet->fx_dy -= h * (pet->state_t < 2.6f ? 22.0f : 5.0f);
        pet->fx_sq += (h - .45f) * -.08f;
    }
    if (pet->anim == PC_ANIM_NONE) return;
    pet->anim_t += dt;
    t = pet->anim_t;
    switch (pet->anim) {
    case PC_ANIM_WAKE:
        if (t < .35f) pet->fx_sq = .22f * sinf(t / .35f * PI * .5f);
        else if (t < .75f) { float x = (t - .35f) / .4f; pet->fx_sq = .22f - .50f * x; pet->fx_dy = -34.0f * sinf(x * PI); }
        else if (t < 1.3f) { float x = (t - .75f) / .55f; pet->fx_sq = -.28f * (1.0f - x) * cosf(x * 15.0f); }
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_CELEBRATE:
    case PC_ANIM_BOUNCE:
        if (t < .42f) { float x = t / .42f; pet->fx_dy = -24.0f * sinf(x * PI); pet->fx_sq = -.12f * sinf(x * PI); }
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_FAIL:
        if (t < .6f) pet->fx_shake = sinf(t * 60.0f) * 5.0f * (1.0f - t / .6f);
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_ALLOWED:
        if (t < .7f) { float x = t / .7f; pet->fx_dy = 7.0f * sinf(x * TAU); pet->fx_tilt = .03f * sinf(x * TAU); }
        else pet->anim = PC_ANIM_NONE;
        break;
    case PC_ANIM_DENIED:
        if (t < .7f) pet->fx_tilt = .20f * sinf(t / .7f * TAU * 2.0f) * (1.0f - t / .7f);
        else pet->anim = PC_ANIM_NONE;
        break;
    default:
        pet->anim = PC_ANIM_NONE;
        break;
    }
}

static void update_particles(pet_t *pet, float dt) {
    int i;
    for (i = 0; i < PET_MAX_PARTICLES; i++) {
        pet_particle_t *q = &pet->parts[i];
        if (q->life <= 0.0f) continue;
        q->life -= dt;
        q->x += q->vx * dt;
        q->y += q->vy * dt;
        q->rot += q->vr * dt;
        if (q->type == P_CONFETTI) q->vy += 320.0f * dt;
        if (q->type == P_DROP) q->vy += 110.0f * dt;
    }
}

void pet_update(pet_t *pet, float dt) {
    const pet_pose_t *k = &k_pose[pet->state];
    pet_pose_t *p = &pet->p;
    float a = 1.0f - expf(-dt * 10.0f), slow = 1.0f - expf(-dt * 5.0f);
    float breath_rate = (pet->state == PC_AG_SLEEPING || pet->state == PC_AG_OFFLINE) ? 1.5f : 2.5f;
    float mouth_open = k->mouth_open;
    float arm_r = k->arm_r, arm_l = k->arm_l;
    float eye_open = k->eye_open;

    if (dt > .1f) dt = .1f;
    pet->t += dt;
    pet->state_t += dt;

    update_look(pet, dt);
    update_blink(pet, dt);

    if (pet->state == PC_AG_TALKING) mouth_open = .10f + .30f * fabsf(sinf(pet->t * 11.0f)) * fabsf(sinf(pet->t * 3.1f));
    if (pet->state == PC_AG_EDITING) arm_r += .25f * sinf(pet->t * 17.0f);
    if (pet->state == PC_AG_SUCCESS) { float w = .35f * sinf(pet->t * 12.0f); arm_l += w; arm_r -= w; }
    if (pet->state == PC_AG_IDLE && sinf(pet->t * .37f) > .985f) arm_r = .9f + .25f * sinf(pet->t * 14.0f); /* the odd wave */

#define EASE(f, rate) p->f += (k->f - p->f) * (rate)
    EASE(eye_w, a); EASE(eye_h, a); EASE(brow, a); EASE(mouth_curve, a); EASE(mouth_w, a);
    EASE(squash, a); EASE(tilt, slow); EASE(happy, a); EASE(closed, a); EASE(blush, slow);
    EASE(dim, slow); EASE(r, slow); EASE(g, slow); EASE(b, slow);
#undef EASE
    p->eye_open += (eye_open - p->eye_open) * a;
    p->mouth_open += (mouth_open - p->mouth_open) * a;
    p->arm_l += (arm_l - p->arm_l) * a;
    p->arm_r += (arm_r - p->arm_r) * a;
    p->look_x += (pet->look_x - p->look_x) * (1.0f - expf(-dt * 16.0f));
    p->look_y += (pet->look_y - p->look_y) * (1.0f - expf(-dt * 16.0f));

    /* damped springs: squash pop and antenna inertia */
    {
        float acc = -180.0f * pet->sq - 13.0f * pet->sq_v;
        pet->sq_v += acc * dt;
        pet->sq += pet->sq_v * dt * .12f;
        acc = -130.0f * pet->ant - 7.0f * pet->ant_v;
        acc += sinf(pet->t * breath_rate) * 4.0f - pet->fx_tilt * 240.0f - pet->fx_shake * 8.0f;
        pet->ant_v += acc * dt;
        pet->ant += pet->ant_v * dt;
    }

    update_anim(pet, dt);
    emit_state_particles(pet, dt);
    update_particles(pet, dt);
}

/* ---- drawing --------------------------------------------------------- */
typedef struct {
    float cx, cy, sx, sy, c, s;
} xf_t;

static inline vec2_t xf(const xf_t *t, float x, float y) {
    vec2_t o;
    float px = x * t->sx, py = y * t->sy;
    o.x = t->cx + px * t->c - py * t->s;
    o.y = t->cy + px * t->s + py * t->c;
    return o;
}

static void draw_body(const pet_t *pet, const xf_t *t, float s) {
    enum { N = 48 };
    static vec2_t shape[N]; /* the outline only needs computing once */
    static int shape_ready;
    vec2_t pts[N];
    const pet_pose_t *p = &pet->p;
    float d = p->dim;
    int i;
    if (!shape_ready) {
        for (i = 0; i < N; i++) {
            float th = (float)i * TAU / (float)N;
            float c = cosf(th), sn = sinf(th);
            float ex = 2.0f / 2.7f;
            float x = (c < 0 ? -1.0f : 1.0f) * powf(fabsf(c), ex) * 76.0f;
            float y = (sn < 0 ? -1.0f : 1.0f) * powf(fabsf(sn), ex) * 64.0f;
            shape[i].x = x * (1.0f + .07f * y / 64.0f); /* slightly pear shaped */
            shape[i].y = y;
        }
        shape_ready = 1;
    }
    for (i = 0; i < N; i++) pts[i] = xf(t, shape[i].x, shape[i].y);
    gfx_path_add(pts, N);
    {
        float tr = 244 * d + p->r * 6, tg = 241 * d + p->g * 6, tb = 233 * d + p->b * 6;
        float br = 196 * d + p->r * 26, bg = 192 * d + p->g * 26, bb = 196 * d + p->b * 26;
        gfx_path_fill_vgrad(GFX_RGB((int)clampf(tr, 0, 255), (int)clampf(tg, 0, 255), (int)clampf(tb, 0, 255)),
                            GFX_RGB((int)clampf(br, 0, 255), (int)clampf(bg, 0, 255), (int)clampf(bb, 0, 255)),
                            t->cy - 64 * s, t->cy + 64 * s);
    }
}

static void draw_arc_eye(const xf_t *t, float ex, float ey, float up, float w) {
    enum { N = 11 };
    vec2_t pts[N];
    int i;
    for (i = 0; i < N; i++) {
        float u = (float)i / (N - 1) * 2.0f - 1.0f;
        pts[i] = xf(t, ex + u * 13.0f, ey + up * (u * u - 1.0f) * 9.0f + up * 3.0f);
    }
    gfx_stroke(pts, N, w, GFX_RGB(26, 26, 34));
}

static void draw_eye(const pet_t *pet, const xf_t *t, float side) {
    enum { N = 28 };
    vec2_t pts[N];
    const pet_pose_t *p = &pet->p;
    float ex = side * 27.0f + p->look_x * 5.0f, ey = -6.0f + p->look_y * 4.0f;
    float open = p->eye_open * (1.0f - pet->blink);
    float rx = 12.0f * p->eye_w, ry = 18.0f * p->eye_h * (open < .07f ? .07f : open);
    float b = p->brow, slope = -side * b * .42f;
    float lid = ey - ry * (1.0f - fabsf(b) * .42f);
    int i;
    if (p->happy > .5f) { draw_arc_eye(t, side * 27.0f, -8.0f, 1.0f, 5.0f); return; }
    if (p->closed > .5f) { draw_arc_eye(t, side * 27.0f, -5.0f, -1.0f, 4.0f); return; }
    for (i = 0; i < N; i++) {
        float th = (float)i * TAU / (float)N;
        float x = ex + rx * cosf(th), y = ey + ry * sinf(th);
        float ly = lid + slope * (x - ex);
        if (fabsf(b) > .02f && y < ly) y = ly;
        pts[i] = xf(t, x, y);
    }
    gfx_path_add(pts, N);
    gfx_path_fill(GFX_RGB(26, 26, 34));
    if (open > .35f) {
        vec2_t h = xf(t, ex + p->look_x * 3.5f - 3.6f, ey - ry * .42f + p->look_y * 2.5f);
        vec2_t h2 = xf(t, ex + p->look_x * 2.0f + 3.8f, ey + ry * .38f + p->look_y * 1.5f);
        float s = t->sy;
        gfx_ellipse(h.x, h.y, 4.4f * s, 4.8f * s, GFX_RGBA(255, 255, 255, 245));
        gfx_ellipse(h2.x, h2.y, 2.0f * s, 2.2f * s, GFX_RGBA(255, 255, 255, 170));
    }
}

static void draw_mouth(const pet_t *pet, const xf_t *t) {
    enum { N = 13 };
    vec2_t up[N], poly[2 * N];
    const pet_pose_t *p = &pet->p;
    float w = 14.0f * p->mouth_w, y = 25.0f;
    int i;
    for (i = 0; i < N; i++) {
        float u = (float)i / (N - 1) * 2.0f - 1.0f, f = 1.0f - u * u;
        up[i].x = u * w;
        up[i].y = y + (p->mouth_curve * (f - .5f)) * 10.0f;
    }
    if (p->mouth_open < .05f) {
        vec2_t ln[N];
        for (i = 0; i < N; i++) ln[i] = xf(t, up[i].x, up[i].y);
        gfx_stroke(ln, N, 3.4f, GFX_RGB(26, 26, 34));
        return;
    }
    for (i = 0; i < N; i++) {
        float u = (float)i / (N - 1) * 2.0f - 1.0f, f = 1.0f - u * u;
        poly[i] = xf(t, up[i].x, up[i].y - 1.2f);
        poly[2 * N - 1 - i] = xf(t, up[i].x, up[i].y + 1.2f + f * p->mouth_open * 26.0f);
    }
    gfx_path_add(poly, 2 * N);
    gfx_path_fill(GFX_RGB(58, 28, 42));
    if (p->mouth_open > .22f) {
        vec2_t c = xf(t, 0, y + p->mouth_open * 19.0f + (p->mouth_curve * .5f) * 10.0f);
        gfx_ellipse(c.x, c.y, w * .52f * t->sx, p->mouth_open * 8.5f * t->sy, GFX_RGB(236, 112, 126));
    }
}

static void draw_arm(const pet_t *pet, const xf_t *t, float side, float raise) {
    float a = (-raise) * 1.15f + .15f;
    vec2_t base = xf(t, side * 68.0f, 12.0f);
    vec2_t tip = xf(t, side * (68.0f + cosf(a) * 28.0f), 12.0f + sinf(a) * 28.0f);
    float d = pet->p.dim;
    gfx_capsule_add(base.x, base.y, tip.x, tip.y, 9.0f * t->sy);
    gfx_path_fill(GFX_RGB((int)(214 * d), (int)(211 * d), (int)(208 * d)));
}

static void draw_antenna(const pet_t *pet, const xf_t *t) {
    enum { N = 7 };
    vec2_t pts[N], tip;
    const pet_pose_t *p = &pet->p;
    float d = p->dim, pulse = .75f + .25f * sinf(pet->t * 3.2f);
    int i;
    for (i = 0; i < N; i++) {
        float u = (float)i / (N - 1);
        float x = pet->ant * 26.0f * u * u, y = -60.0f - u * 32.0f;
        pts[i] = xf(t, x, y);
    }
    gfx_stroke(pts, N, 4.2f * t->sy, GFX_RGB((int)(206 * d), (int)(203 * d), (int)(200 * d)));
    tip = pts[N - 1];
    gfx_ellipse(tip.x, tip.y, 13.0f * t->sy, 13.0f * t->sy, pet_accent(pet, (int)(70 * pulse)));
    gfx_ellipse(tip.x, tip.y, 6.6f * t->sy, 6.6f * t->sy, pet_accent(pet, 255));
    gfx_ellipse(tip.x - 2.0f, tip.y - 2.2f, 1.9f * t->sy, 1.9f * t->sy, GFX_RGBA(255, 255, 255, 215));
}

static void draw_props(pet_t *pet, const xf_t *t, float s) {
    float now = pet->t;
    vec2_t c;
    int i;
    switch (pet->state) {
    case PC_AG_THINKING:
        for (i = 0; i < 3; i++) {
            float ph = sinf(now * 4.0f - (float)i * .9f) * .5f + .5f;
            c = xf(t, 74.0f + (float)i * 15.0f, -56.0f - (float)i * 16.0f);
            gfx_ellipse(c.x, c.y, (3.2f + (float)i * 2.2f) * s, (3.2f + (float)i * 2.2f) * s, pet_accent(pet, 120 + (int)(135 * ph)));
        }
        break;
    case PC_AG_EDITING: {
        float px = t->cx + 104.0f * s, py = t->cy - 46.0f * s, typed = fmodf(now * 1.1f, 6.0f);
        gfx_rrect(px, py, 72.0f * s, 84.0f * s, 9.0f * s, GFX_RGBA(30, 34, 48, 240));
        for (i = 0; i < 6; i++) {
            static const float w[6] = {44, 30, 52, 24, 38, 48};
            static const float ind[6] = {0, 8, 8, 16, 8, 0};
            float k = clampf(typed - (float)i, 0, 1), ww = w[i] * k * s;
            float y = py + (12.0f + (float)i * 11.5f) * s, x = px + (9.0f + ind[i]) * s;
            if (ww > 1.0f) gfx_rrect(x, y, ww, 5.0f * s, 2.5f * s, i % 2 ? GFX_RGBA(214, 218, 232, 230) : pet_accent(pet, 245));
            if (k > 0.0f && k < 1.0f && sinf(now * 22.0f) > -.4f) gfx_rrect(x + ww + 2.0f, y - 2.0f * s, 2.5f * s, 9.0f * s, 1.0f, GFX_RGB(255, 255, 255));
        }
        break;
    }
    case PC_AG_WORKING:
    case PC_AG_RUNNING:
    case PC_AG_TESTING: {
        float a = now * 6.0f;
        c = xf(t, 112.0f, -38.0f);
        gfx_ring(c.x, c.y, 21.0f * s, 6.0f * s, 0, TAU, GFX_RGBA(255, 255, 255, 34));
        gfx_ring(c.x, c.y, 21.0f * s, 6.0f * s, a, a + 3.6f, pet_accent(pet, 255));
        if (pet->state == PC_AG_TESTING) {
            int lit = (int)fmodf(now * 3.0f, 6.0f);
            for (i = 0; i < 5; i++) {
                vec2_t d = xf(t, 88.0f + (float)i * 12.0f, -6.0f);
                gfx_ellipse(d.x, d.y, 3.8f * s, 3.8f * s, i < lit ? GFX_RGB(96, 232, 150) : GFX_RGBA(255, 255, 255, 60));
            }
        } else {
            gfx_text_center(gfx_font_body, (int)c.x, (int)c.y - 8, pet->state == PC_AG_RUNNING ? ">_" : "::", pet_accent(pet, 240));
        }
        break;
    }
    case PC_AG_APPROVAL: {
        float b = fabsf(sinf(now * 7.0f)) * 5.0f;
        vec2_t top = xf(t, -92.0f, -74.0f - b), bot = xf(t, -92.0f, -48.0f - b), dot = xf(t, -92.0f, -34.0f - b);
        gfx_capsule_add(top.x, top.y, bot.x, bot.y, 5.6f * s);
        gfx_path_fill(pet_accent(pet, 255));
        gfx_ellipse(dot.x, dot.y, 5.4f * s, 5.4f * s, pet_accent(pet, 255));
        break;
    }
    case PC_AG_TALKING: {
        vec2_t bb = xf(t, 84.0f, -84.0f);
        gfx_rrect(bb.x, bb.y, 62.0f * s, 34.0f * s, 12.0f * s, GFX_RGBA(255, 255, 255, 232));
        for (i = 0; i < 3; i++) {
            float y = sinf(now * 7.0f - (float)i) * 3.0f * s;
            gfx_ellipse(bb.x + (17.0f + (float)i * 14.0f) * s, bb.y + 17.0f * s + y, 3.8f * s, 3.8f * s, pet_accent(pet, 255));
        }
        break;
    }
    case PC_AG_FAILED: {
        static const float ox[5] = {-30, -13, 6, 26, -2}, oy[5] = {-86, -95, -97, -87, -82}, rr[5] = {14, 18, 20, 15, 22};
        for (i = 0; i < 5; i++) {
            c = xf(t, ox[i], oy[i]);
            gfx_ellipse(c.x, c.y, rr[i] * s, rr[i] * .72f * s, GFX_RGB(92, 96, 112));
        }
        break;
    }
    default:
        break;
    }
}

static void draw_particles(pet_t *pet, const xf_t *t, float s) {
    int i;
    for (i = 0; i < PET_MAX_PARTICLES; i++) {
        const pet_particle_t *q = &pet->parts[i];
        vec2_t c;
        float k;
        if (q->life <= 0.0f) continue;
        c = xf(t, q->x, q->y);
        k = clampf(q->life / q->max, 0, 1);
        switch (q->type) {
        case P_Z:
            gfx_text(q->size > 1.0f ? gfx_font_title : gfx_font_body, (int)c.x, (int)c.y, "z", GFX_RGBA(190, 200, 255, (int)(210 * k)));
            break;
        case P_CONFETTI: {
            vec2_t r[4];
            float co = cosf(q->rot), si = sinf(q->rot), w = q->size * s, h = q->size * .55f * s;
            r[0].x = c.x + co * w - si * h; r[0].y = c.y + si * w + co * h;
            r[1].x = c.x - co * w - si * h; r[1].y = c.y - si * w + co * h;
            r[2].x = c.x - co * w + si * h; r[2].y = c.y - si * w - co * h;
            r[3].x = c.x + co * w + si * h; r[3].y = c.y + si * w - co * h;
            gfx_path_add(r, 4);
            gfx_path_fill((q->color & 0xFFFFFFu) | ((uint32_t)(255 * clampf(k * 2.0f, 0, 1)) << 24));
            break;
        }
        case P_DROP:
            gfx_ellipse(c.x, c.y, 3.4f * s, 5.0f * s, GFX_RGBA(120, 200, 255, (int)(235 * k)));
            break;
        case P_RAIN: {
            vec2_t e = xf(t, q->x - .8f, q->y + 9.0f);
            gfx_capsule_add(c.x, c.y, e.x, e.y, 1.2f * s);
            gfx_path_fill(GFX_RGBA(130, 170, 255, 230));
            break;
        }
        default:
            break;
        }
    }
}

void pet_draw(pet_t *pet, float cx, float cy, float scale) {
    const pet_pose_t *p = &pet->p;
    float breath = sinf(pet->t * ((pet->state == PC_AG_SLEEPING || pet->state == PC_AG_OFFLINE) ? 1.5f : 2.5f));
    float sq = p->squash + pet->fx_sq + pet->sq + breath * .016f;
    float hover = (pet->state == PC_AG_OFFLINE || pet->state == PC_AG_SLEEPING) ? 0.0f : sinf(pet->t * 1.7f) * 3.0f;
    float y = cy + (pet->fx_dy + hover) * scale;
    float tilt = p->tilt + pet->fx_tilt;
    float pulse = .86f + .14f * breath;
    xf_t t;
    t.cx = cx + pet->fx_shake * scale;
    t.cy = y;
    t.sx = scale * (1.0f + sq);
    t.sy = scale * (1.0f - sq);
    t.c = cosf(tilt);
    t.s = sinf(tilt);

    if (pet->quality > 0) gfx_ellipse(cx, y, 128.0f * scale * pulse, 104.0f * scale * pulse, pet_accent(pet, 16));
    gfx_ellipse(cx, y, 98.0f * scale, 84.0f * scale, pet_accent(pet, 26));
    {
        float lift = clampf(-pet->fx_dy / 34.0f, 0, 1);
        gfx_ellipse(cx, cy + 78.0f * scale, 66.0f * scale * (1.0f - lift * .35f), 8.5f * scale * (1.0f - lift * .35f), pet_accent(pet, 74 - (int)(lift * 34)));
    }

    draw_arm(pet, &t, -1.0f, p->arm_l);
    draw_arm(pet, &t, 1.0f, p->arm_r);
    draw_antenna(pet, &t);
    draw_body(pet, &t, scale);

    if (p->blush > .03f) {
        vec2_t l = xf(&t, -49.0f, 14.0f), r = xf(&t, 49.0f, 14.0f);
        int a = (int)(112 * clampf(p->blush, 0, 1));
        gfx_ellipse(l.x, l.y, 11.5f * t.sx, 7.0f * t.sy, GFX_RGBA(255, 140, 150, a));
        gfx_ellipse(r.x, r.y, 11.5f * t.sx, 7.0f * t.sy, GFX_RGBA(255, 140, 150, a));
    }
    draw_eye(pet, &t, -1.0f);
    draw_eye(pet, &t, 1.0f);
    draw_mouth(pet, &t);
    draw_props(pet, &t, scale);
    draw_particles(pet, &t, scale);
}
