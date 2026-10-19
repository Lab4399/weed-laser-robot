# OpenMV 视觉版固件 v2（重构自 openmv_vision_only_main.py DRAFT）
# 中心绿色细矩形瞄准框 + 中心十字瞄点 + 杂草检测
# + 目标相对瞄点的偏移与坐标范围 + 定点坐标输出给 F407 控制舵机
#
# 新增（相对 DRAFT 原版）：
#   1) 中央绿色细矩形瞄准框 + 中心十字瞄点
#   2) 相对中心偏移 dx/dy（原版只发归一化绝对坐标 0-100）
#   3) 目标框四角相对中心的坐标范围
#   4) G/B 坐标帧，全部 <= 31 字节，匹配 F407 行缓冲上限 32
# 修复：
#   5) 显式设置曝光增益（原版只关 auto 不给值 -> 画面发黑、阈值失效）
#   6) 补心跳（原版无心跳 -> F407 看门狗 1500ms 会停舵机）
#   7) 补异常兜底；删除永不生效的 detector 死代码
#
# 协议（行尾 \n）：
#   G,<dx>,<dy>,<cls>,<conf>  目标中心相对瞄点偏移 + 类别 + 置信度
#   B,<x0>,<y0>,<x1>,<y1>    目标框四角相对瞄点的坐标范围
#   R                        无目标
#   RDY / PING               握手与心跳
#   D,<cnt>,<cx>,<cy>        旧归一化坐标（PROTOCOL_LEGACY=True 时发）
#   dx>0 偏右；dy>0 偏下。cls: 1=weed 可打，0=crop 不可打。conf: 0-100
#   帧长实测: G,-160,-120,1,99\n=16B   B,-180,-140,180,140\n=20B
#
# 只发坐标，不动电机与激光：执行层归 F407（架构 C）。
#
# 单文件自包含：瞄准几何已内联（原 vision_core.py 保留在同目录，
# 仅供 PC 端离线复算参考，运行时不依赖它，避免芯片上 import 路径问题）。

import sensor, image, time, pyb
from pyb import UART

# ══ 瞄准几何（内联自 vision_core.py）═══════════════════════════════════════
FRAME_W, FRAME_H = 320, 240
CENTER_X, CENTER_Y = FRAME_W // 2, FRAME_H // 2   # (160, 120)
AIM_BOX_W = 44            # 中央瞄准框宽（像素）
AIM_BOX_H = 32            # 中央瞄准框高
AIM_BOX_THICK = 1         # 细矩形框
AIM_DEADZONE_PX = 8       # 判定"已对准"的半径


def aim_box_rect():
    return (CENTER_X - AIM_BOX_W // 2,
            CENTER_Y - AIM_BOX_H // 2, AIM_BOX_W, AIM_BOX_H)


def offset_of(cx, cy):
    return cx - CENTER_X, cy - CENTER_Y


def box_range(bx, by, bw, bh):
    x0 = bx - CENTER_X
    y0 = by - CENTER_Y
    return x0, y0, x0 + bw, y0 + bh


def in_deadzone(dx, dy, radius=AIM_DEADZONE_PX):
    return abs(dx) <= radius and abs(dy) <= radius


def clamp_offset(dx, dy):
    dx = max(-CENTER_X, min(CENTER_X, dx))
    dy = max(-CENTER_Y, min(CENTER_Y, dy))
    return dx, dy


UART_BAUDRATE = 115200
UART_PORT = 3
SEND_HZ = 10
HEARTBEAT_MS = 1000
PROTOCOL_LEGACY = False

COLOR_AIM = (0, 255, 0)
COLOR_TARGET = (255, 0, 0)
COLOR_TEXT = (255, 255, 255)

EXPOSURE_CALIBRATE = False
EXPOSURE_US = 12000
GAIN_DB = 4

MIN_APHID_COUNT = 1
DETECTION_CONFIG = {
    'leaf':  {'threshold': (20, 100, -60, -10, -30, 60), 'min_pixels': 200, 'min_area': 300},
    'aphid': {'threshold': (0, 40, -25, 15, -25, 20), 'min_size': 12, 'max_size': 220},
}
TARGET_AREA_MIN = 200
TARGET_AREA_MAX = 26000
DEBUG_DRAW = True

_active_uart = None


def find_leaf(img):
    cfg = DETECTION_CONFIG['leaf']
    blobs = img.find_blobs([cfg['threshold']], pixels_threshold=cfg['min_pixels'],
                           area_threshold=cfg['min_area'], merge=True)
    return max(blobs, key=lambda b: b.area()) if blobs else None


def find_aphids(img, leaf):
    if leaf is None:
        return []
    x, y, w, h = leaf.rect()
    cfg = DETECTION_CONFIG['aphid']
    pad = 2
    roi = (x + pad, y + pad, max(w - 2 * pad, 1), max(h - 2 * pad, 1))
    try:
        blobs = img.find_blobs([cfg['threshold']], pixels_threshold=cfg['min_size'],
                               area_threshold=cfg['min_size'], merge=False, roi=roi)
    except Exception as e:
        print('[detect] error:', e)
        return []
    out = []
    for b in blobs:
        a = b.area()
        if cfg['min_size'] <= a <= cfg['max_size'] and TARGET_AREA_MIN <= a <= TARGET_AREA_MAX:
            out.append(b)
    return out


def classify(area):
    """端侧类别过滤：只有判为 weed 才上报 cls=1。"""
    if area < TARGET_AREA_MIN or area > TARGET_AREA_MAX:
        return 0, 0
    if area <= 4000:
        return 1, max(35, min(90, int(area * 90 // 4000)))
    return 0, 20


def init_sensor():
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    if EXPOSURE_CALIBRATE:
        sensor.set_auto_gain(True)
        sensor.set_auto_whitebal(True)
        sensor.set_auto_exposure(True)
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 1500:
            sensor.snapshot()
        print('[calib] auto-converged: exposure_us=%d gain_db=%d'
              % (sensor.get_exposure_us(), sensor.get_gain_db()))
    else:
        sensor.set_auto_gain(False)
        sensor.set_auto_whitebal(False)
        sensor.set_auto_exposure(False)
        # 必须显式给值，否则增益锁在偏暗默认值，画面发黑、阈值失效
        sensor.set_gain_db(GAIN_DB)
        sensor.set_exposure_us(EXPOSURE_US)
    for _ in range(20):
        sensor.snapshot()
    print('[boot] %dx%d exp=%dus gain=%ddB center=(%d,%d) aimbox=%dx%d'
          % (sensor.width(), sensor.height(), sensor.get_exposure_us(),
             sensor.get_gain_db(), CENTER_X, CENTER_Y,
             AIM_BOX_W, AIM_BOX_H))


def send(line):
    global _active_uart
    if _active_uart is None:
        return
    try:
        if len(line) > 31:
            print('[send] frame too long, rejected:', line)
            return
        _active_uart.write((line + '\n').encode('ascii', 'ignore'))
    except Exception as e:
        print('[send] error:', e)


def draw_aim(img):
    """中央绿色细矩形瞄准框 + 中心十字瞄点。"""
    bx, by, bw, bh = aim_box_rect()
    img.draw_rectangle(bx, by, bw, bh, color=COLOR_AIM, thickness=AIM_BOX_THICK)
    img.draw_cross(CENTER_X, CENTER_Y, color=COLOR_AIM, size=10, thickness=2)
    img.draw_string(4, 4, "AIM %dx%d" % (AIM_BOX_W, AIM_BOX_H), color=COLOR_AIM)


def draw_target(img, blob, dx, dy, cls, conf):
    """目标框 + 从瞄点到目标的偏移指示线 + 数值。"""
    x, y, w, h = blob.rect()
    col = COLOR_TARGET if cls == 1 else (255, 160, 0)
    img.draw_rectangle(x, y, w, h, color=col, thickness=2)
    img.draw_line(CENTER_X, CENTER_Y, blob.cx(), blob.cy(), color=col, thickness=1)
    tx = max(0, min(blob.cx() - 60, 200))
    ty = max(0, blob.cy() - 26)
    img.draw_string(tx, ty, "dx%d dy%d" % (dx, dy), color=COLOR_TEXT)
    img.draw_string(tx, ty + 12, "cls%d c%d" % (cls, conf), color=COLOR_TEXT)


def main():
    global _active_uart
    init_sensor()
    _active_uart = UART(UART_PORT, UART_BAUDRATE)

    send("RDY")
    print("[Vision] only sends coords; F407 owns motors and laser")

    last_send = 0
    interval = 1000 // SEND_HZ
    last_ping = time.ticks_ms()
    send_box = True
    hit = 0

    while True:
        img = sensor.snapshot()

        # 心跳：F407 看门狗 1500ms，缺帧会停舵机
        if time.ticks_diff(time.ticks_ms(), last_ping) >= HEARTBEAT_MS:
            send("PING")
            last_ping = time.ticks_ms()

        leaf = find_leaf(img)
        aphids = find_aphids(img, leaf) if leaf else []
        count = len(aphids)

        if DEBUG_DRAW:
            draw_aim(img)
            if leaf is not None:
                lx, ly, lw, lh = leaf.rect()
                img.draw_rectangle(lx, ly, lw, lh, color=COLOR_TARGET, thickness=1)

        now = time.ticks_ms()
        if time.ticks_diff(now, last_send) >= interval:
            last_send = now
            if count >= MIN_APHID_COUNT:
                tgt = max(aphids, key=lambda b: b.area())
                cls, conf = classify(tgt.area())
                dx, dy = clamp_offset(*offset_of(tgt.cx(), tgt.cy()))

                if PROTOCOL_LEGACY:
                    send("D,%d,%d,%d" % (count,
                                        int(tgt.cx() * 100 / img.width()),
                                        int(tgt.cy() * 100 / img.height())))
                else:
                    send("G,%d,%d,%d,%d" % (dx, dy, cls, conf))
                    # 坐标范围帧与主帧交替发，降低 F407 侧解析负担
                    send_box = not send_box
                    if send_box:
                        send("B,%d,%d,%d,%d" % box_range(*tgt.rect()))

                if DEBUG_DRAW:
                    draw_target(img, tgt, dx, dy, cls, conf)

                hit = hit + 1 if in_deadzone(dx, dy) else 0
                if hit == 30:
                    print("[ok] 30 consecutive frames inside deadzone")
                    hit = 0
            else:
                send("R")


def safe_exit():
    try:
        send("STOP")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nuser abort")
    except Exception as e:
        print("\n[fatal]", e)
        try:
            import sys
            sys.print_exception(e)
        except Exception:
            pass
    finally:
        safe_exit()
        print("[Vision] exited")
