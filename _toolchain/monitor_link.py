# -*- coding: utf-8 -*-
r"""
monitor_link.py —— 本地运行状态监听器（无需 ST-Link）

用途
----
电池供电、脱开 PC 时，整台机器由 OpenMV + F407 两颗芯片自主运行。
想看清它们的状态，传统做法是接 ST-Link 读 F407 —— 但那需要 ST-Link 驱动，
而本机驱动装不上（CM_PROB_FAILED_INSTALL，见 docs/机箱现状与运行状态核查.md）。

本脚本走另一条路：**从 COM4 读 OpenMV 的诊断输出**。
OpenMV 固件（openmv/main_diag.py）会把 F407 链路状态每秒上报一次：

    [diag] seq=12 st=SCAN f407=Y ok+1 err+0 silent=420ms(OK) tgt_area=0 lock=0 shots=0/0/0 dry=ON

由此可以判断：
  * F407 是否在线（f407=Y/N，来自 READY 握手）
  * 命令有没有被接受（ok/err 增量，err 频繁说明帧格式有问题）
  * 看门狗风险（silent 逼近 1500ms 就会被 F407 强制关激光）
  * 当前状态机状态、目标面积、发射预算
  * 激光是否处于 DRY_RUN 安全态

前提
----
1. OpenMV 已烧录 openmv/main_diag.py（复制到芯片 J 盘 main.py）
2. OpenMV 与 PC 的 USB 线接着（COM4）
3. **OpenMV IDE 不能同时占用 COM4**

用法
----
    python _toolchain\monitor_link.py                    # 默认 COM4，无超时
    python _toolchain\monitor_link.py --port COM4 --secs 30
    python _toolchain\monitor_link.py --csv out.csv      # 同时存 CSV 便于分析

注意
----
DRY_RUN=True 时 FIRE 会被固件拦下换成 L0，不会出光。
看到 dry=ON 才是安全态；dry=OFF 时 laser_off 之外的路径都可能真开激光。
"""

import argparse
import csv
import os
import re
import sys
import time

import serial

DIAG_RE = re.compile(
    r"\[diag\]\s+seq=(\d+)\s+st=(\S+)\s+f407=(\S)\s+ok\+(\d+)\s+err\+(\d+)\s+"
    r"silent=(\d+)ms\((\w+)\)\s+tgt_area=(\d+)\s+lock=(\d+)\s+"
    r"shots=(\d+)/(\d+)/(\d+)\s+dry=(\w+)"
)
STAT_RE = re.compile(r"\[stat\]\s+fps=(\d+)\s+state=(\S+)")


def hr(t):
    print("\n" + "=" * 70)
    print(f"  {t}")
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='COM4')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--secs', type=float, default=0, help='0 = 一直跑到 Ctrl+C')
    ap.add_argument('--csv', default=None, help='把 diag 帧存成 CSV')
    a = ap.parse_args()

    hr("OpenMV ⇄ F407 链路监听")
    print(f"  端口 {a.port} @ {a.baud}")
    print("  前提：OpenMV IDE 未占用该串口；芯片上跑的是 main_diag.py")
    print("  退出：Ctrl+C")
    print()

    try:
        s = serial.Serial(a.port, a.baud, timeout=1)
    except serial.SerialException as e:
        print(f"❌ 打不开 {a.port}：{e}")
        print()
        print("  常见原因：")
        print("   1) OpenMV IDE 正连着这个串口 —— 关掉 IDE 的连接或退出 IDE")
        print("   2) 端口号不对 —— 用 --list 看有哪些串口")
        print("   3) USB 线只供电不通信 —— 换一根数据线")
        return
    s.reset_input_buffer()

    csvf = None
    if a.csv:
        csvf = open(a.csv, 'w', newline='', encoding='utf-8')
        w = csv.writer(csvf)
        w.writerow(['ts', 'seq', 'state', 'f407', 'ok_delta', 'err_delta',
                    'silent_ms', 'watchdog', 'tgt_area', 'lock',
                    'per_target', 'minute', 'total', 'dry'])
        print(f"  CSV 输出：{a.csv}")

    # 统计
    n_diag = n_err_delta = 0
    total_err = total_ok = 0
    lost_f407 = 0
    wd_risk = 0
    states = {}
    t0 = time.time()
    last_print = 0.0

    print(f"  {'序号':>6} {'状态':<8} {'F407':>5} {'OK':>4} {'ERR':>4} "
          f"{'静默':>8} {'看门狗':>6} {'面积':>7} {'发射':>10} {'激光':>5}")
    print("  " + "-" * 74)

    try:
        while True:
            if a.secs and time.time() - t0 > a.secs:
                break
            raw = s.readline()
            if not raw:
                continue
            line = raw.decode('utf-8', errors='replace').rstrip()

            m = DIAG_RE.search(line)
            if m:
                (seq, st, f407, okd, errd, silent, wd,
                 area, lock, pt, mn, tot, dry) = m.groups()
                seq, okd, errd, silent, area = map(int, (seq, okd, errd, silent, area))
                n_diag += 1
                total_ok += okd
                total_err += errd
                if f407 != 'Y':
                    lost_f407 += 1
                if wd != 'OK':
                    wd_risk += 1
                states[st] = states.get(st, 0) + 1

                # 异常行高亮
                flag = ''
                if errd:
                    flag = '  ⚠ ERR'
                if wd != 'OK':
                    flag += '  ⚠ 看门狗风险'
                if f407 != 'Y':
                    flag += '  ⚠ F407 离线'
                print(f"  {seq:>6} {st:<8} {f407:>5} {okd:>4} {errd:>4} "
                      f"{silent:>6}ms {wd:>6} {area:>7} {pt}/{mn}/{tot:>7} {dry:>5}{flag}")

                if csvf:
                    csvf.writerow([time.strftime('%H:%M:%S'), seq, st, f407,
                                   okd, errd, silent, wd, area, lock,
                                   pt, mn, tot, dry])
                    csvf.flush()
                last_print = time.time()
                continue

            # 其他行按原文显示（boot / link / safe / detect 等）
            if line.startswith('['):
                print(f"  {line}")

    except KeyboardInterrupt:
        print("\n\n  用户中断")
    finally:
        s.close()
        if csvf:
            csvf.close()

    hr("监听汇总")
    dur = time.time() - t0
    print(f"  运行时长        {dur:.1f} s")
    print(f"  诊断帧          {n_diag} 条（期望 ~{int(dur)} 条/秒）")
    print(f"  F407 应答 OK    {total_ok} 次")
    print(f"  F407 应答 ERR   {total_err} 次"
          + ("  ⚠ 偏多，检查帧格式" if total_err > max(5, total_ok * 0.05) else ""))
    print(f"  F407 离线帧     {lost_f407} 次" + ("  ⚠ F407 没握手成功" if lost_f407 else "  ✅ 全程在线"))
    print(f"  看门狗风险      {wd_risk} 次"
          + ("  ⚠ 静默逼近 1500ms，F407 会强制关激光" if wd_risk else "  ✅ 心跳正常"))
    if states:
        top = sorted(states.items(), key=lambda x: -x[1])[:6]
        print(f"  状态分布        " + ", ".join(f"{k} {v}" for k, v in top))
    print()
    if n_diag == 0:
        print("  ❌ 一条诊断帧都没收到")
        print("     确认芯片上跑的是 main_diag.py（不是原版 main.py），")
        print("     原版只有每 5 秒一次的 [stat]，本脚本不解析它。")


if __name__ == '__main__':
    main()