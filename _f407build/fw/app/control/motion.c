/**
 * @file    motion.c
 * @brief   运动控制实现
 *
 * ── 本文件最重要的一件事：把"期望值"与"实际输出值"分开 ──
 *
 *   motion_command() 算出 desired，motion_tick() 把 applied 逐步逼近期望值。
 *   这个分离是加速度限制（slew）能成立的前提。
 *
 *   如果直接输出算法结果，那么目标在画面里跳一下（例如识别框抖动），
 *   占空比就会从 +700 一步跳到 -700。履带电机在这种反向冲击下
 *   堵转电流可达额定值的 5~10 倍，几分钟内烧掉驱动板是常态。
 *
 *   所以 CTRL_SLEW_STEP_DEFAULT 这个参数比 Kp 更关键。
 */
#include "motion.h"
#include "../Core/app_config.h"
#include "../drivers/motor.h"

#include <math.h>

static motion_params_t s_par;
static motion_state_t  s_st;
static bool            s_stop_requested;

/* ------------------------------------------------------------------------- */
static inline int16_t clamp_i16(int32_t v, int32_t lo, int32_t hi)
{
    return (int16_t)((v < lo) ? lo : ((v > hi) ? hi : v));
}

/* ---------------------------------------------------------------------------
 * 接近程度评估
 *
 * 双目测距有效时用真实距离；未标定时退化为"目标框占画面高度的比例"。
 * 后者不能给出绝对距离，但足以实现"目标看起来变大就减速"这一基本行为。
 * 在双目标定完成前，这比"凭感觉设一个固定速度"安全得多。
 * ------------------------------------------------------------------------- */
static float estimate_near(const VisionTarget *t)
{
    if (t == NULL || t->cls == VCLS_NONE) return 0.0f;

    if (t->dist_mm > 0) {
        /* 300 mm 以内 = 很近，1200 mm 以外 = 很远 */
        float d = (float)t->dist_mm;
        float s = (1200.0f - d) / (1200.0f - 300.0f);
        if (s < 0.0f) s = 0.0f;
        if (s > 1.0f) s = 1.0f;
        return s;
    }

    /* 单目代理：框高 / 画面高 */
    float ratio = (float)t->height / (float)LINK_IMG_HEIGHT;
    float s = (ratio - 0.10f) / (0.60f - 0.10f);
    if (s < 0.0f) s = 0.0f;
    if (s > 1.0f) s = 1.0f;
    return s;
}

/* ------------------------------------------------------------------------- */
void motion_init(void)
{
    s_par.base_speed   = CTRL_BASE_SPEED_DEFAULT;
    s_par.kp_turn      = CTRL_KP_TURN_DEFAULT;
    s_par.deadzone_px  = CTRL_CENTER_DEADZONE_PX;
    s_par.slew_step    = CTRL_SLEW_STEP_DEFAULT;
    s_par.duty_max     = CTRL_DUTY_MAX;

    s_st.left_desired = 0;
    s_st.right_desired = 0;
    s_st.left_applied = 0;
    s_st.right_applied = 0;
    s_st.near_score = 0.0f;
    s_st.turn = 0.0f;

    s_stop_requested = false;
}

void motion_get_params(motion_params_t *out)
{
    if (out) *out = s_par;
}

void motion_set_params(const motion_params_t *in)
{
    if (in == NULL) return;

    /* 逐项限幅。参数可能来自外部命令或 Flash，不能假设它们合法。
     * 一个 base_speed = 5000 的参数会让小车满速冲出赛道，
     * 而现象看起来像"控制算法疯了"，实际只是配置没校验。 */
    s_par.base_speed = clamp_i16(in->base_speed,
                                 CTRL_BASE_SPEED_MIN, CTRL_BASE_SPEED_MAX);

    float kp = in->kp_turn;
    if (kp < CTRL_KP_TURN_MIN) kp = CTRL_KP_TURN_MIN;
    if (kp > CTRL_KP_TURN_MAX) kp = CTRL_KP_TURN_MAX;
    s_par.kp_turn = kp;

    s_par.deadzone_px = clamp_i16(in->deadzone_px, 0, LINK_IMG_WIDTH / 2);
    s_par.slew_step   = clamp_i16(in->slew_step,
                                  CTRL_SLEW_STEP_MIN, CTRL_SLEW_STEP_MAX);
    s_par.duty_max    = clamp_i16(in->duty_max, 0, CTRL_DUTY_MAX);
}

void motion_request_stop(void)
{
    s_stop_requested = true;
    s_st.left_desired = 0;
    s_st.right_desired = 0;
}

void motion_get_state(motion_state_t *out)
{
    if (out) *out = s_st;
}

/* ---------------------------------------------------------------------------
 * 主控制律
 * ------------------------------------------------------------------------- */
void motion_command(const VisionTarget *t, uint32_t lost_frames)
{
    if (s_stop_requested) {
        s_st.left_desired = 0;
        s_st.right_desired = 0;
        return;
    }

    /* --- 情形 1：目标丢失 ---
     * 短暂丢失（叶片遮挡、光照突变）不应立刻停车 —— 那会让小车一顿一顿地走。
     * 先保持，再降速，最后停。阈值来自 SAFETY_LOST_FRAMES_*。 */
    if (t == NULL || t->cls == VCLS_NONE || lost_frames > 0) {
        if (lost_frames <= SAFETY_LOST_FRAMES_SLOW) {
            /* 保持上一次的期望值不动 */
            return;
        }
        if (lost_frames <= SAFETY_LOST_FRAMES_STOP) {
            /* 线性降速到基础速度的 40% */
            int16_t slow = (int16_t)(s_par.base_speed * 4 / 10);
            s_st.left_desired = slow;
            s_st.right_desired = slow;
            return;
        }
        /* 长时间无目标：停车，等待（可能由 safety 转入搜索状态） */
        s_st.left_desired = 0;
        s_st.right_desired = 0;
        return;
    }

    /* --- 情形 2：看到作物 ---
     * 除草机器人压过作物等于作业失败。看到作物且在画面中央区域时直接停，
     * 把处置权交给 safety（可由上层决定是转向绕开还是停车报警）。 */
    if (t->cls == VCLS_CROP) {
        int32_t absx = (t->err_x < 0) ? -(int32_t)t->err_x : (int32_t)t->err_x;
        if (absx < (LINK_IMG_WIDTH / 2)) {
            s_st.left_desired = 0;
            s_st.right_desired = 0;
            return;
        }
        /* 作物在画面边缘：只要不撞上去，可以继续作业，但降速 */
    }

    /* --- 情形 3：正常跟踪 --- */
    float err = t->err_x;

    /* 死区处理：减去死区宽度而不是直接判零，
     * 否则目标从 |err| = deadzone+1 移到 deadzone-1 时转向量会跳变，
     * 表现为小车在直行时有规律的左右抽搐。 */
    float turn_input = 0.0f;
    float dz = (float)s_par.deadzone_px;
    if (err > dz)       turn_input =  err - dz;
    else if (err < -dz) turn_input =  err + dz;

    float turn = s_par.kp_turn * turn_input;

    /* 接近度调制：越近越慢 */
    float near = estimate_near(t);
    s_st.near_score = near;
    float speed_scale = 1.0f - 0.60f * near;

    /* 置信度调制：置信度不高时不允许激进动作。
     * 这是协议文档第 9 节"置信度低于阈值时不允许产生激进运动控制"的落地。 */
    if (t->confidence < SAFETY_CONF_DEGRADE) {
        speed_scale *= 0.60f;
        turn *= 0.60f;
    }

    int32_t base = (int32_t)((float)s_par.base_speed * speed_scale);

    s_st.turn = turn;
    s_st.left_desired  = clamp_i16(base + (int32_t)turn, -s_par.duty_max, s_par.duty_max);
    s_st.right_desired = clamp_i16(base - (int32_t)turn, -s_par.duty_max, s_par.duty_max);
}

/* ---------------------------------------------------------------------------
 * 限速输出
 * ------------------------------------------------------------------------- */
static inline int16_t slew(int16_t cur, int16_t desired, int16_t step)
{
    int32_t diff = (int32_t)desired - (int32_t)cur;
    if (diff > step)  diff = step;
    if (diff < -step) diff = -step;
    return (int16_t)((int32_t)cur + diff);
}

void motion_tick(void)
{
    s_st.left_applied  = slew(s_st.left_applied,  s_st.left_desired,  s_par.slew_step);
    s_st.right_applied = slew(s_st.right_applied, s_st.right_desired, s_par.slew_step);

    motor_set_both(s_st.left_applied, s_st.right_applied);
}
