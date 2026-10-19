# -*- coding: utf-8 -*-
"""
verify_f407.py —— F407 新版固件运行时验证（不烧录）

前提：fw407.elf 已用 pyocd CLI 烧录（--erase sector 路径）。
本脚本做：
  1. 连接并 halt
  2. 设 DBGMCU_CR.DBG_IWDG_STOP（ halted 期间冻结看门狗）
  3. 清零 .noinit 的连续 IWDG 复位计数（防上电即 FAULT）
  4. 读核心/外设/应用层状态并判读
  5. 恢复运行
"""
import sys
import time

from pyocd.core.helpers import ConnectHelper

ADDR = {
    "s_state":              0x20001347,
    "s_estop":              0x20001345,
    "s_uptime_ms":          0x2000133c,
    "s_last_frame_ms":      0x20001340,
    "s_iwdg_reset_streak":  0x200018b4,
    "ul_irq_count":         0x20000fa0,
    "ul_bytes_rx":          0x20000fa4,
    "ul_ring_overflow":     0x20000fa8,
    "ul_dma_err":           0x20000fac,
    "ul_ore_err":           0x20000fb0,
    "vp_frames_ok":         0x20000f4c,
    "vp_err_crc":           0x20000f50,
    "vp_err_field":         0x20000f54,
    "vp_err_range":         0x20000f58,
    "vp_err_len":           0x20000f5c,
    "vp_err_class":         0x20000f60,
    "vp_seq_gap":           0x20000f64,
}
REG = {
    "USART1_SR":   0x40011000,
    "USART1_BRR":  0x40011008,
    "USART1_CR1":  0x4001100C,
    "USART1_CR3":  0x40011014,
    "TIM3_CR1":    0x40000400,
    "TIM4_CR1":    0x40000800,
    "RCC_CFGR":    0x40023808,
    "DBGMCU_CR":   0xE0042004,
}
STATE_NAME = {0: "INIT", 1: "IDLE", 2: "AUTO", 3: "SAFE_STOP", 4: "FAULT"}


def hexs(v):
    return f"0x{v:08X}"


def main():
    session = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f407zgtx",
        connect_mode="attach",
    )
    if session is None:
        print("!! 没找到 ST-Link")
        return 1

    with session:
        t = session.target
        print(f"[连接] {t.part_number}  探针: {session.probe.unique_id}")

        t.halt()
        dbg = t.read32(REG["DBGMCU_CR"])
        t.write32(REG["DBGMCU_CR"], dbg | 0x100)
        print(f"[DBG ] DBG_IWDG_STOP = {'ON' if t.read32(REG['DBGMCU_CR']) & 0x100 else 'OFF'}")

        t.write32(ADDR["s_iwdg_reset_streak"], 0)
        print(f"[NOINIT] streak = {t.read32(ADDR['s_iwdg_reset_streak'])}")

        pc = t.read_core_register("pc")
        sp = t.read_core_register("sp")
        print(f"\n[核心] PC={hexs(pc)} SP={hexs(sp)} "
              f"PC在Flash={'OK' if 0x08000000 <= pc < 0x08100000 else '!!异常'}")

        r = {k: t.read32(v) for k, v in REG.items() if k != "DBGMCU_CR"}
        print("\n--- 外设 ---")
        print(f"RCC_CFGR   = {hexs(r['RCC_CFGR'])}  期望 0x0000940A {'OK' if r['RCC_CFGR']==0x940A else '!!'}")
        cr1 = r["USART1_CR1"]
        print(f"USART1_CR1 = {hexs(cr1)}  UE={'ON' if cr1&0x2000 else 'OFF!!'} "
              f"TE={'ON' if cr1&8 else 'OFF'} RE={'ON' if cr1&4 else 'OFF'} "
              f"IDLEIE={'ON' if cr1&0x10 else 'OFF!!'}")
        print(f"USART1_BRR = {hexs(r['USART1_BRR'])}  期望 0x000002D9 {'OK' if r['USART1_BRR']==0x2D9 else '!!'}")
        cr3 = r["USART1_CR3"]
        print(f"USART1_CR3 = {hexs(cr3)}  EIE={'ON' if cr3&1 else 'OFF'} DMAR={'ON' if cr3&0x40 else 'OFF!!'}")
        print(f"TIM3_CR1   = {hexs(r['TIM3_CR1'])}  CEN={'ON' if r['TIM3_CR1']&1 else 'OFF!!'}")
        print(f"TIM4_CR1   = {hexs(r['TIM4_CR1'])}  CEN={'ON' if r['TIM4_CR1']&1 else 'OFF!!'}")

        print("\n--- 应用层 ---")
        st = t.read8(ADDR["s_state"])
        # ⚠️ 采样间隔内必须让 CPU 真正跑起来。
        # 原写法是 halt 状态下 sleep 0.4s 再读——停机时 s_uptime_ms 当然不变，
        # 于是把"任务在跑"误判成"卡死"。这类假阴性比没检查更糟：
        # 它会让人去修一个根本不存在的问题。
        u1 = t.read32(ADDR["s_uptime_ms"])
        t.resume()
        time.sleep(0.4)
        t.halt()
        u2 = t.read32(ADDR["s_uptime_ms"])
        print(f"s_state     = {st} ({STATE_NAME.get(st,'?')})")
        print(f"s_uptime_ms = {u1} -> {u2}  {'OK 任务在跑' if u2>u1 else '!! 不增长'}")
        print(f"s_estop     = {t.read8(ADDR['s_estop'])}")

        ul = {k: t.read32(ADDR[k]) for k in ADDR if k.startswith("ul_")}
        print(f"uart_link   : {ul}")
        vp = {k: t.read32(ADDR[k]) for k in ADDR if k.startswith("vp_")}
        print(f"vision_proto: {vp}")

        # ---- 结论 ----
        print("\n--- 判读 ---")
        ok = True
        ok &= (r["USART1_CR1"] & 0x201C) == 0x201C
        ok &= (r["USART1_CR3"] & 0x41) == 0x41
        ok &= (r["TIM3_CR1"] & 1) == 1 and (r["TIM4_CR1"] & 1) == 1
        ok &= u2 > u1
        if ok:
            print("PASS —— 固件运行正常，USART1 视觉链路已使能。")
            print("       把 OpenMV UART3(P4=TX/P5=RX) 交叉接到 F407 PA10/PA9 并共地，")
            print("       然后重跑本脚本看 vp_frames_ok 是否增长。")
        else:
            print("FAIL —— 有项目未达标，见上面 !! 项。")

        t.resume()
        print("\n[完成] 已恢复运行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
