# -*- coding: utf-8 -*-
# ============================================================================
#  main.py —— OpenMV H7-50V8 T6 视觉节点主循环
#
#  主链路：
#      采集 → 识别 → 选目标 → 测距 → 组帧 → UART → F407
#                    └→ 云台舵机闭环（视觉内环）
#
#  ── 关于"推理很慢"这件事 ──────────────────────────────────────────
#  MCU 上的推理延迟可能是几百毫秒（参考文献中 STM32U5 上 224×224 输入的单帧
#  推理达 1510 ms）。而协议要求 50 ms 发一帧，两者直接冲突。
#
#  解决方案：把"发送"从"推理"里解耦。
#      · 推理结束后立刻把结果发出去（这是新鲜数据）
#      · 推理进行中，按 HEARTBEAT_MS 重发上一次的结果（这是心跳）
#      · 无目标时发 CLASS=NONE
#
#  为什么心跳要"重发上一次的结果"而不是发 NONE：
#      发 NONE 会让 F407 认为目标消失，从而减速/搜索；
#      而实际上目标就在那里，只是这一帧还没算完。
#      重发上一次结果 = "保持上次指令"，这在 300 ms 内是正确行为。
#
#  ⚠️ 由此推导出 F407 侧的一个硬约束：
#      LINK_TIMEOUT_MS 必须 > 单帧推理最坏耗时 × 1.5
#      否则每次推理都会触发误超时，小车一顿一顿地走。
#      标定方法：让 OpenMV 打印单帧推理耗时，取最大值填入 F407 配置。
# ============================================================================

import time
import sensor
import image
import pyb

import config
import detector as detector_mod
import tracker
import ranging
import servo as servo_mod
import uart_protocol


def init_camera():
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    # QQVGA(160x120) / QVGA(320x240) / VGA(640x480)
    # 分辨率直接决定推理耗时。先用 QVGA 与 F407 默认的 320 保持协议一致。
    sensor.set_framesize(sensor.QVGA)
    if config.CAM_WINDOWING:
        sensor.set_windowing(config.CAM_WINDOWING)
    sensor.set_auto_gain(True)
    sensor.set_auto_whitebal(True)
    # 关掉自动曝光抖动对颜色阈值的干扰（blob 模式尤其敏感）
    sensor.skip_frames(time=1500)


def init_uart():
    if config.UART_TX_PIN and config.UART_RX_PIN:
        uart = pyb.UART(config.UART_ID, config.UART_BAUD,
                        timeout=config.UART_TIMEOUT_MS,
                        timeout_char=config.UART_TIMEOUT_MS)
        uart.init(config.UART_BAUD, bits=8, parity=None, stop=1,
                  pins=(config.UART_TX_PIN, config.UART_RX_PIN))
    else:
        uart = pyb.UART(config.UART_ID, config.UART_BAUD,
                        timeout=config.UART_TIMEOUT_MS,
                        timeout_char=config.UART_TIMEOUT_MS)
    return uart


def main():
    init_camera()
    uart = init_uart()

    det = detector_mod.Detector()
    rng = ranging.StereoRanger()
    gimbal = servo_mod.Gimbal()
    lost = tracker.LostCounter()
    builder = uart_protocol.FrameBuilder(uart)

    INFER_PERIOD_MS = 200        # 两次推理之间的最小间隔，防止跑满 CPU

    last_infer = time.ticks_ms()
    last_tx = time.ticks_ms()

    # 最近一次的有效作业结果，供心跳重发
    last_payload = ("NONE", 0.0, 0, 0, 0, 0, 0)

    tick = time.ticks_ms()
    infer_count = 0
    infer_ms_max = 0
    img_h = 240

    print("=== weeding car vision node up ===")
    print("detector=%s uart=%d baud=%d" % (det.mode, config.UART_ID, config.UART_BAUD))

    while True:
        now = time.ticks_ms()

        if time.ticks_diff(now, last_infer) >= INFER_PERIOD_MS:
            # ---------- 1. 采集 ----------
            t0 = time.ticks_ms()
            img = sensor.snapshot()
            img_h = img.height()

            # ---------- 2. 识别 ----------
            targets = det.detect(img)

            # ---------- 3. 选唯一目标 ----------
            best = tracker.select(targets)
            lost.update(best)

            # ---------- 4. 测距 ----------
            # 视差需要立体匹配结果，标定完成前恒为 0
            dist_mm = rng.dist(best, disparity_px=0)

            # ---------- 5. 云台闭环（视觉内环） ----------
            gimbal.update(best, img.width())

            # ---------- 6. 组装载荷 ----------
            if best is not None:
                last_payload = (builder.CLS_WEED, best.conf,
                                best.cx, best.cy, best.w, best.h, dist_mm)
            else:
                last_payload = (builder.CLS_NONE, 0.0, 0, 0, 0, 0, 0)

            infer_ms = time.ticks_diff(time.ticks_ms(), t0)
            if infer_ms > infer_ms_max:
                infer_ms_max = infer_ms
            infer_count += 1
            last_infer = time.ticks_ms()

            if config.DEBUG_PRINT and (infer_count % config.DEBUG_EVERY_N == 0):
                # 这行输出的 infer_ms_max 就是 F407 侧 LINK_TIMEOUT_MS 的取值依据
                print("infer=%4dms max=%4dms lost=%d gimbal=%s det=%s" % (
                    infer_ms, infer_ms_max, lost.frames,
                    gimbal.stats()[0], det.stats()))

        # ---------- 7. 发送（心跳与结果统一走这里） ----------
        if time.ticks_diff(now, last_tx) >= config.HEARTBEAT_MS:
            cls, conf, cx, cy, w, h, dist = last_payload
            builder.send_target(cls, conf, cx, cy, w, h, dist)
            last_tx = now

        # 注意：这里不要加 pyb.wfi() 或 sleep。
        # 本循环是"轮询 + 阻塞式推理"模型，插入休眠会推迟 UART 发送时刻，
        # 让 F407 侧的心跳间隔变得不确定。CPU 占用高一点没关系，
        # 但发送时刻的规律性是这个链路的安全基础。
        # 若实测 CPU 跑满导致帧率过低，正确做法是调大 INFER_PERIOD_MS
        # 或降低推理分辨率，而不是在这里加休眠。


if __name__ == "__main__":
    main()
