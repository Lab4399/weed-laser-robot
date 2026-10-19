# -*- coding: utf-8 -*-
"""
flash_f407_v2.py —— 烧录新版 F407 固件（视觉链路版）并做运行时验证

与旧版 flash_f407.py 的区别：
  1. 烧录的是 _f407build/fw/build/fw407.elf（带 USART1 视觉链路的新固件），
     不再是 Good_Dog；
  2. 烧录前设置 DBGMCU_CR 的 DBG_IWDG_STOP 位 —— 否则 halted 期间
     IWDG（500ms）继续计数，会在验证读取过程中把芯片复位掉；
  3. 烧录后清零 .noinit 里的连续 IWDG 复位计数（防上电即 FAULT 锁死）；
  4. 验证清单：USART1 CR1/CR3/BRR、TIM3/TIM4 CEN、RCC CFGR、
     以及应用层运行时变量（s_state / s_uptime_ms / uart_link stats /
     vision_proto stats）。

用法：
    D:\\AI\\python\\envs\\train\\Scripts\\python.exe flash_f407_v2.py
"""
import sys
import time

from pyocd.core.helpers import ConnectHelper
from pyocd.flash.file_programmer import FileProgrammer

ELF = r"E:\PlantDiseaseProject\_f407build\fw\build\fw407.elf"

# ---- 运行时符号地址（来自 fw407.elf 的 nm 输出 + gdb 结构体偏移）----
ADDR = {
    # 系统/安全
    "s_state":           0x20001347,   # 1B: 0=INIT 1=IDLE 2=AUTO 3=SAFE_STOP 4=FAULT
    "s_estop":           0x20001345,   # 1B
    "s_uptime_ms":       0x2000133c,   # 4B safety 任务毫秒计数（增长即任务在跑）
    "s_last_frame_ms":   0x20001340,   # 4B
    "s_iwdg_reset_streak": 0x200018b4, # 4B .noinit，烧录后必须清零
    # uart_link 统计（s_stats +0..4: irq_count, bytes_rx, ring_overflow, dma_err, ore_err）
    "ul_irq_count":      0x20000fa0,
    "ul_bytes_rx":       0x20000fa4,
    "ul_ring_overflow":  0x20000fa8,
    "ul_dma_err":        0x20000fac,
    "ul_ore_err":        0x20000fb0,
    # vision_proto 统计（s_proto+0x84: frames_ok, err_crc, err_field,
    #                    err_range, err_len, err_class, seq_gap, ...）
    "vp_frames_ok":      0x20000f4c,
    "vp_err_crc":        0x20000f50,
    "vp_err_field":      0x20000f54,
    "vp_err_range":      0x20000f58,
    "vp_err_len":        0x20000f5c,
    "vp_err_class":      0x20000f60,
    "vp_seq_gap":        0x20000f64,
    # 外设句柄
    "huart1":            0x20001448,
    "hdma_usart1_rx":    0x200013e4,
    "htim3":             0x2000139c,
    "htim4":             0x20001354,
    "hiwdg":             0x20001348,
}

# ---- 外设寄存器（F407 参考手册 RM0090）----
REG = {
    "USART1_SR":   0x40011000,
    "USART1_DR":   0x40011004,
    "USART1_BRR":  0x40011008,
    "USART1_CR1":  0x4001100C,
    "USART1_CR2":  0x40011010,
    "USART1_CR3":  0x40011014,
    "TIM3_CR1":    0x40000400,
    "TIM3_CCMR1":  0x40000418,
    "TIM3_CCER":   0x40000420,
    "TIM4_CR1":    0x40000800,
    "TIM4_CCMR1":  0x40000818,
    "TIM4_CCER":   0x40000820,
    "RCC_CFGR":    0x40023808,
    "RCC_CR":      0x40023800,
    "DBGMCU_CR":   0xE0042004,
}

STATE_NAME = {0: "INIT", 1: "IDLE", 2: "AUTO", 3: "SAFE_STOP", 4: "FAULT"}


def hexs(v):
    return f"0x{v:08X}"


def main():
    print("=" * 64)
    print("烧录 F407 新版固件（USART1 视觉链路 + FreeRTOS + safety）")
    print("=" * 64)

    session = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f407zgtx",
        connect_mode="halt",
        exit_on_error=True,
    )
    if session is None:
        print("!! 没找到 ST-Link，退出")
        return 1

    with session:
        target = session.target
        print(f"[连接] {target.part_number}  探针: {session.probe.unique_id}")

        # ---- 1. 冻结 IWDG（ halted 期间的验证读取不会被狗咬断）----
        dbg = target.read32(REG["DBGMCU_CR"])
        target.write32(REG["DBGMCU_CR"], dbg | (1 << 8))
        dbg2 = target.read32(REG["DBGMCU_CR"])
        print(f"[DBG ] DBGMCU_CR {hexs(dbg)} -> {hexs(dbg2)}  (DBG_IWDG_STOP={'ON' if dbg2 & 0x100 else 'OFF'})")

        # ---- 2. 烧录 ELF ----
        print(f"[烧录] {ELF}")
        t0 = time.time()
        fp = FileProgrammer(session, chip_erase="auto")
        fp.program(ELF)
        print(f"[烧录] 完成，耗时 {time.time()-t0:.1f}s")

        # ---- 3. 清零 .noinit 的 IWDG 连续复位计数 ----
        target.write32(ADDR["s_iwdg_reset_streak"], 0)
        chk = target.read32(ADDR["s_iwdg_reset_streak"])
        print(f"[NOINIT] s_iwdg_reset_streak @ {hexs(ADDR['s_iwdg_reset_streak'])} = {chk}")

        # ---- 4. 复位并运行 ----
        target.reset()
        target.resume()
        print("[运行] 已复位并恢复运行，等待 3 秒让它启动……")
        time.sleep(3.0)

        # ---- 5. Halt 验证 ----
        target.halt()
        pc = target.read_core_register("pc")
        sp = target.read_core_register("sp")
        print()
        print("=" * 64)
        print("运行时验证")
        print("=" * 64)
        print(f"[核心] PC = {hexs(pc)}   SP = {hexs(sp)}")
        print(f"       PC 在 Flash 区: {'OK' if 0x08000000 <= pc < 0x08100000 else '!! 不在 Flash'}")

        r = {k: target.read32(v) for k, v in REG.items()}
        print()
        print("--- 外设寄存器 ---")
        print(f"RCC_CFGR      = {hexs(r['RCC_CFGR'])}   (期望 0x0000940A: SWS=PLL, APB1=/4, APB2=/2)")
        print(f"RCC_CR        = {hexs(r['RCC_CR'])}   (PLLRDY 应在)")
        cr1 = r["USART1_CR1"]
        print(f"USART1_CR1    = {hexs(cr1)}")
        print(f"   UE(0x2000)={'ON' if cr1 & 0x2000 else 'OFF !!'}"
              f"  TE(0x8)={'ON' if cr1 & 0x8 else 'OFF'}"
              f"  RE(0x4)={'ON' if cr1 & 0x4 else 'OFF'}"
              f"  IDLEIE(0x10)={'ON' if cr1 & 0x10 else 'OFF !!'}")
        print(f"USART1_BRR    = {hexs(r['USART1_BRR'])}   (115200@84MHz 期望 0x02D9)")
        cr3 = r["USART1_CR3"]
        print(f"USART1_CR3    = {hexs(cr3)}   EIE(0x1)={'ON' if cr3 & 1 else 'OFF'} DMAR(0x40)={'ON' if cr3 & 0x40 else 'OFF'}")
        t3, t4 = r["TIM3_CR1"], r["TIM4_CR1"]
        print(f"TIM3_CR1      = {hexs(t3)}   CEN={'ON' if t3 & 1 else 'OFF !!'}")
        print(f"TIM4_CR1      = {hexs(t4)}   CEN={'ON' if t4 & 1 else 'OFF !!'}")

        print()
        print("--- 应用层运行时变量 ---")
        st = target.read8(ADDR["s_state"])
        up1 = target.read32(ADDR["s_uptime_ms"])
        time.sleep(0.3)
        up2 = target.read32(ADDR["s_uptime_ms"])
        print(f"s_state       = {st} ({STATE_NAME.get(st, '?')})")
        print(f"s_uptime_ms   = {up1} -> {up2}  ({'增长 OK，safety 任务在跑' if up2 > up1 else '!! 不增长'})")
        print(f"s_estop       = {target.read8(ADDR['s_estop'])}")

        ul = {k: target.read32(ADDR[k]) for k in
              ("ul_irq_count", "ul_bytes_rx", "ul_ring_overflow", "ul_dma_err", "ul_ore_err")}
        print(f"uart_link     : irq={ul['ul_irq_count']} bytes_rx={ul['ul_bytes_rx']} "
              f"ovf={ul['ul_ring_overflow']} dma_err={ul['ul_dma_err']} ore={ul['ul_ore_err']}")

        vp = {k: target.read32(ADDR[k]) for k in
              ("vp_frames_ok", "vp_err_crc", "vp_err_field", "vp_err_range",
               "vp_err_len", "vp_err_class", "vp_seq_gap")}
        print(f"vision_proto  : frames_ok={vp['vp_frames_ok']} err_crc={vp['vp_err_crc']} "
              f"err_field={vp['vp_err_field']} err_range={vp['vp_err_range']} "
              f"err_len={vp['vp_err_len']} err_class={vp['vp_err_class']} seq_gap={vp['vp_seq_gap']}")

        # ---- 6. 恢复运行，断开（芯片继续脱网运行）----
        target.resume()
        print()
        print("[完成] 已恢复运行并断开。芯片现在跑的是新固件。")
        print("       下一步：把 OpenMV 的 UART3(P4/P5) 接到 F407 的 PA9/PA10（交叉、共地），")
        print("       然后看 vp_frames_ok 是否增长。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
