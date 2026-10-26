/**
 * @file    param.c
 * @brief   参数持久化实现
 */
#include "param.h"
#include "../Core/app_config.h"

#include "stm32f4xx_hal.h"
#include <string.h>

/* ---------------------------------------------------------------------------
 * 存储布局
 *
 * 每个 Bank 的头部放校验信息，后面跟 payload。
 * crc32 覆盖 version..payload 的全部字节（不含 magic 与 crc32 自身）。
 * ------------------------------------------------------------------------- */
typedef struct {
    uint32_t magic;      /* PARAM_MAGIC */
    uint32_t version;    /* 结构体版本，用于将来做迁移 */
    uint32_t seq;        /* 单调递增序号，乒乓的核心 */
    uint32_t crc32;      /* 覆盖 version / seq / payload */
    param_payload_t payload;
    uint32_t tail_guard; /* 固定值，用于检测"写到一半掉电" */
} param_bank_t;

#define PARAM_TAIL_GUARD   0xA5A55A5AU

static const uint32_t s_bank_addr[2] = { PARAM_BANK_A_ADDR, PARAM_BANK_B_ADDR };
static const uint32_t s_bank_sector[2] = { FLASH_SECTOR_10, FLASH_SECTOR_11 };

static param_payload_t s_cur;
static bool s_was_lost;
static uint32_t s_cur_seq;
static int8_t  s_cur_bank;      /* 当前有效数据所在 Bank，-1 = 无 */

/* ---------------------------------------------------------------------------
 * CRC-32 (poly 0x04C11DB7, 反射写法 0xEDB88320)，与常见工具链一致
 * ------------------------------------------------------------------------- */
static uint32_t crc32_calc(const uint8_t *data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t b = 0; b < 8; b++) {
            crc = (crc & 1u) ? ((crc >> 1) ^ 0xEDB88320u) : (crc >> 1);
        }
    }
    return ~crc;
}

static uint32_t bank_crc32(const param_bank_t *b)
{
    /* 从 version 字段开始，覆盖到 payload 结束 */
    const uint8_t *p = (const uint8_t *)&b->version;
    uint32_t len = (uint32_t)((const uint8_t *)&b->payload + sizeof(b->payload) - p);
    return crc32_calc(p, len);
}

/* ---------------------------------------------------------------------------
 * Bank 有效性判定
 * ------------------------------------------------------------------------- */
static bool bank_valid(const param_bank_t *b)
{
    if (b->magic != PARAM_MAGIC) return false;
    if (b->version != PARAM_VERSION) return false;
    if (b->tail_guard != PARAM_TAIL_GUARD) return false;   /* 半截写入 */
    if (bank_crc32(b) != b->crc32) return false;
    return true;
}

/* ---------------------------------------------------------------------------
 * 出厂默认值
 * ------------------------------------------------------------------------- */
void param_load_defaults(void)
{
    memset(&s_cur, 0, sizeof(s_cur));

    s_cur.motion.base_speed  = CTRL_BASE_SPEED_DEFAULT;
    s_cur.motion.kp_turn     = CTRL_KP_TURN_DEFAULT;
    s_cur.motion.deadzone_px = CTRL_CENTER_DEADZONE_PX;
    s_cur.motion.slew_step   = CTRL_SLEW_STEP_DEFAULT;
    s_cur.motion.duty_max    = CTRL_DUTY_MAX;

    for (int i = 0; i < PARAM_SERVO_LIMITS; i++) {
        s_cur.servo_a[i] = SERVO_PULSE_CENTER_US;
        s_cur.servo_b[i] = SERVO_PULSE_CENTER_US;
    }
    /* 默认让 min/center/max 有合理的展开，便于首次上电后直接微调 */
    s_cur.servo_a[0] = SERVO_PULSE_MIN_US;
    s_cur.servo_a[2] = SERVO_PULSE_MAX_US;
    s_cur.servo_b[0] = SERVO_PULSE_MIN_US;
    s_cur.servo_b[2] = SERVO_PULSE_MAX_US;
}

/* ---------------------------------------------------------------------------
 * 参数校验
 *
 * 所有进入 Flash 的值都必须在这里过一遍。
 * 一个越界的 base_speed 会在下次上电时表现为"控制算法疯了"，
 * 而实际上算法没问题 —— 排查方向会被完全带偏。
 * ------------------------------------------------------------------------- */
static bool validate(param_payload_t *p)
{
    if (p->motion.base_speed < CTRL_BASE_SPEED_MIN ||
        p->motion.base_speed > CTRL_BASE_SPEED_MAX) return false;

    if (p->motion.kp_turn < CTRL_KP_TURN_MIN ||
        p->motion.kp_turn > CTRL_KP_TURN_MAX) return false;

    if (p->motion.slew_step < CTRL_SLEW_STEP_MIN ||
        p->motion.slew_step > CTRL_SLEW_STEP_MAX) return false;

    if (p->motion.duty_max < 0 || p->motion.duty_max > CTRL_DUTY_MAX) return false;
    if (p->motion.deadzone_px < 0 ||
        p->motion.deadzone_px > (LINK_IMG_WIDTH / 2)) return false;

    for (int k = 0; k < 2; k++) {
        const uint16_t *a = (k == 0) ? p->servo_a : p->servo_b;
        for (int i = 0; i < PARAM_SERVO_LIMITS; i++) {
            if (a[i] < SERVO_PULSE_MIN_US || a[i] > SERVO_PULSE_MAX_US) return false;
        }
        /* 必须满足 min <= center <= max，否则限幅逻辑会产生
         * "目标值永远达不到"的现象（表现为舵机缓慢顶死在一侧） */
        if (!(a[0] <= a[1] && a[1] <= a[2])) return false;
    }
    return true;
}

/* ---------------------------------------------------------------------------
 * 初始化：挑出有效且序号最大的 Bank
 * ------------------------------------------------------------------------- */
void param_init(void)
{
    s_was_lost = false;
    s_cur_bank = -1;
    s_cur_seq = 0;

    const param_bank_t *best = NULL;
    int8_t best_idx = -1;

    for (int i = 0; i < 2; i++) {
        /* 用 uintptr_t 中转：Cortex-M 上 Flash 地址是 32 位整数常量，
         * 直接转指针在 64 位主机做语法检查时会触发 -Wint-to-pointer-cast */
        const param_bank_t *b =
            (const param_bank_t *)(uintptr_t)s_bank_addr[i];
        if (!bank_valid(b)) continue;
        if (best == NULL || b->seq > best->seq) {
            best = b;
            best_idx = (int8_t)i;
        }
    }

    if (best == NULL) {
        /* 两份都无效：可能是首次烧录（全 0xFF），也可能是双份同时损坏。
         * 前者是正常现象，后者是故障。区分方法：看是否曾经写成功过。
         * 这里保守处理 —— 记标志，由上层决定是否上报故障。 */
        param_load_defaults();
        s_cur_seq = 0;
        s_cur_bank = -1;
        s_was_lost = true;
        return;
    }

    s_cur = best->payload;
    s_cur_seq = best->seq;
    s_cur_bank = best_idx;

    if (!validate(&s_cur)) {
        param_load_defaults();
        s_was_lost = true;
    }
}

void param_get(param_payload_t *out)
{
    if (out) *out = s_cur;
}

bool param_set(const param_payload_t *in)
{
    if (in == NULL) return false;
    param_payload_t tmp = *in;
    if (!validate(&tmp)) return false;
    s_cur = tmp;
    return true;
}

bool param_was_lost(void)
{
    return s_was_lost;
}

/* ---------------------------------------------------------------------------
 * 写入
 * ------------------------------------------------------------------------- */
static bool flash_erase_bank(int idx)
{
    FLASH_EraseInitTypeDef er;
    uint32_t sector_err = 0;

    er.TypeErase    = FLASH_TYPEERASE_SECTORS;
    er.VoltageRange = FLASH_VOLTAGE_RANGE_3;
    er.Sector       = s_bank_sector[idx];
    er.NbSectors    = 1;

    HAL_FLASH_Unlock();
    HAL_StatusTypeDef st = HAL_FLASHEx_Erase(&er, &sector_err);
    HAL_FLASH_Lock();

    return (st == HAL_OK) && (sector_err == 0xFFFFFFFFu);
}

static bool flash_write_bank(int idx, const param_bank_t *b)
{
    const uint32_t *src = (const uint32_t *)b;
    uint32_t addr = s_bank_addr[idx];
    uint32_t words = (sizeof(param_bank_t) + 3u) / 4u;

    HAL_FLASH_Unlock();
    for (uint32_t i = 0; i < words; i++) {
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, addr, src[i]) != HAL_OK) {
            HAL_FLASH_Lock();
            return false;
        }
        addr += 4u;
    }
    HAL_FLASH_Lock();
    return true;
}

bool param_save(void)
{
    /* 目标 Bank = 当前有效 Bank 的另一个。
     * 若当前没有有效 Bank（s_cur_bank == -1），写 A。 */
    int target = (s_cur_bank == 0) ? 1 : 0;

    param_bank_t b;
    memset(&b, 0, sizeof(b));
    b.magic      = PARAM_MAGIC;
    b.version    = PARAM_VERSION;
    b.seq        = s_cur_seq + 1u;
    b.payload    = s_cur;
    b.tail_guard = PARAM_TAIL_GUARD;
    b.crc32      = bank_crc32(&b);

    if (!flash_erase_bank(target)) {
        return false;
    }
    if (!flash_write_bank(target, &b)) {
        return false;
    }

    /* 回读校验。不能只信 HAL 的返回值 —— 写保护、电压不足、
     * 扇区被 RDP 保护等情况都可能让 Program 返回成功但数据不对。 */
    const param_bank_t *rb =
        (const param_bank_t *)(uintptr_t)s_bank_addr[target];
    if (!bank_valid(rb) || rb->seq != b.seq) {
        return false;
    }

    s_cur_seq  = b.seq;
    s_cur_bank = (int8_t)target;
    s_was_lost = false;
    return true;
}

int8_t param_current_bank(void)
{
    return s_cur_bank;
}

uint32_t param_current_seq(void)
{
    return s_cur_seq;
}
