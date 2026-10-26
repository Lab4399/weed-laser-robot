# -*- coding: utf-8 -*-
"""扫描 F407：Flash 内容比对 + 运行时状态快照。

只读，不写 Flash、不改任何寄存器（除必要的 halt/resume）。
"""
import os
import re
import struct
import subprocess
import sys
import time

from pyocd.core.helpers import ConnectHelper

ELF = r"E:\PlantDiseaseProject\_f407build\fw\build\fw407.elf"
BIN = r"E:\PlantDiseaseProject\_f407build\fw\build\fw407.bin"
NM = (r"E:\STM32\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins"
      r"\com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740"
      r"\tools\bin\arm-none-eabi-nm.exe")


def symbols():
    out = subprocess.run([NM, "-S", ELF], capture_output=True, text=True).stdout
    d = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 4:
            d[p[3]] = (int(p[0], 16), int(p[1], 16))
        elif len(p) == 3:
            d[p[2]] = (int(p[0], 16), 0)
    return d


def main():
    sym = symbols()

    session = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f407zgtx", connect_mode="halt", exit_on_error=False)
    if session is None:
        print("连接失败")
        return 1
    session.open()
    t = session.target
    t.halt()

    print("=" * 66)
    print("  一、芯片身份")
    print("=" * 66)
    cpuid = t.read32(0xE000ED00)
    devid = t.read32(0x5C001000) if False else t.read32(0x40023C00)  # dummy guard
    # Flash size register @ 0x1FFF7A22
    fsize = t.read16(0x1FFF7A22)
    uid = t.read_memory_block8(0x1FFF7A10, 12)
    print(f"  CPUID      = 0x{cpuid:08X}")
    print(f"  Flash 容量 = {fsize} KB")
    print(f"  UID        = 0x{''.join(f'{b:02X}' for b in uid)}")
    print(f"  向量表 SP  = 0x{t.read32(0x08000000):08X}")
    print(f"  向量表 PC  = 0x{t.read32(0x08000004):08X}")

    print()
    print("=" * 66)
    print("  二、Flash 实际内容 vs 本地构建产物")
    print("=" * 66)
    local = open(BIN, "rb").read()
    flash = bytes(t.read_memory_block8(0x08000000, 0x8000))  # 前 32KB
    print(f"  本地 fw407.bin   : {len(local)} B")
    same = flash[:len(local)] == local
    print(f"  Flash 前 {len(local)} B : {'完全一致' if same else '不一致！'}")
    # 找非 0xFF 末端
    last = max(i for i, b in enumerate(flash) if b != 0xFF)
    print(f"  Flash 有效末端    : 0x{last:04X} ({last + 1} B)")
    # 本地 bin 尾部
    lb = max(i for i, b in enumerate(local) if b != 0xFF)
    print(f"  本地 bin 有效末端 : 0x{lb:04X} ({lb + 1} B)")
    if same:
        print("  => 芯片跑的就是本地这份固件，符号地址可用")

    print()
    print("=" * 66)
    print("  三、CPU 运行时")
    print("=" * 66)
    pc, sp, lr = t.read_core_register("pc"), t.read_core_register("sp"), t.read_core_register("lr")
    xpsr = t.read_core_register("xpsr")
    print(f"  PC   = 0x{pc:08X}   {'Flash 代码区' if 0x08000000 <= pc < 0x08100000 else '非 Flash'}")
    print(f"  SP   = 0x{sp:08X}   {'SRAM 内' if 0x20000000 <= sp <= 0x20020000 else '越界！'}")
    print(f"  LR   = 0x{lr:08X}")
    print(f"  IPSR = {xpsr & 0x1FF}  {'（主任务态）' if (xpsr & 0x1FF) == 0 else '（中断中）'}")

    print()
    print("=" * 66)
    print("  四、时钟与外设")
    print("=" * 66)
    rcc_cr, rcc_cfgr = t.read32(0x40023800), t.read32(0x40023808)
    print(f"  RCC_CR    = 0x{rcc_cr:08X}  PLLRDY={'ON' if rcc_cr & (1 << 25) else 'OFF'}  "
          f"HSERDY={'ON' if rcc_cr & (1 << 17) else 'OFF'}")
    print(f"  RCC_CFGR  = 0x{rcc_cfgr:08X}  SW={rcc_cfgr & 3} "
          f"({'PLL' if (rcc_cfgr & 3) == 2 else 'HSI' if (rcc_cfgr & 3) == 0 else 'HSE'})")

    usart1 = 0x40011000
    cr1, brr, cr3, sr = t.read32(usart1 + 0x0C), t.read32(usart1 + 0x08), t.read32(usart1 + 0x14), t.read32(usart1)
    print(f"  USART1 CR1= 0x{cr1:08X}  UE={'ON' if cr1 & (1 << 13) else 'OFF'} "
          f"TE={'ON' if cr1 & (1 << 3) else 'OFF'} RE={'ON' if cr1 & (1 << 2) else 'OFF'} "
          f"IDLEIE={'ON' if cr1 & (1 << 4) else 'OFF'}")
    print(f"  USART1 BRR= 0x{brr:08X}  波特率≈{84000000 // (brr & 0xFFFF) if brr else 0}")
    print(f"  USART1 CR3= 0x{cr3:08X}  DMAR={'ON' if cr3 & (1 << 6) else 'OFF'}")
    print(f"  USART1 SR = 0x{sr:08X}")

    # 其余串口是否也被打开过
    others = [("USART2", 0x40004400), ("USART3", 0x40004800),
              ("UART4", 0x40004C00), ("UART5", 0x40005000), ("USART6", 0x40011400)]
    live = [(n, t.read32(a + 0x0C)) for n, a in others]
    print(f"  其他串口 CR1: " + "  ".join(f"{n}=0x{v:08X}" for n, v in live))

    tim3, tim4 = t.read32(0x40000400), t.read32(0x40000800)
    print(f"  TIM3_CR1  = 0x{tim3:08X}  CEN={'ON' if tim3 & 1 else 'OFF'}")
    print(f"  TIM4_CR1  = 0x{tim4:08X}  CEN={'ON' if tim4 & 1 else 'OFF'}")
    systick_ctrl = t.read32(0xE000E010)
    print(f"  SysTick   = 0x{systick_ctrl:08X}  ENABLE={'ON' if systick_ctrl & 1 else 'OFF'}")

    gpioa_odr = t.read32(0x40020014)
    gpiod_odr = t.read32(0x40020C14)
    print(f"  GPIOA_ODR = 0x{gpioa_odr:04X}   GPIOA_MODER=0x{t.read32(0x40020000):08X}")
    print(f"  GPIOD_ODR = 0x{gpiod_odr:04X}   GPIOD_MODER=0x{t.read32(0x40020C00):08X}")

    print()
    print("=" * 66)
    print("  五、应用层状态（halt 状态下读第一采样）")
    print("=" * 66)
    a_state = sym["s_state"][0]
    a_fault = sym["s_fault"][0]
    a_uptime = sym["s_uptime_ms"][0]
    a_streak = sym["s_iwdg_reset_streak"][0]
    a_estop = sym["s_estop"][0]
    a_hb = sym["s_hb_last"][0]

    STATES = {0: "INIT", 1: "IDLE", 2: "SCAN", 3: "TRACK", 4: "STRIKE", 5: "FAULT"}
    FAULTS = {0: "NONE", 1: "ESTOP", 2: "TASK_STALL", 3: "LINK_LOST",
              4: "IWDG_LOOP", 5: "PARAM", 6: "OVERCURRENT", 7: "TILT"}

    st = t.read8(a_state)
    fl = t.read8(a_fault)
    up1 = t.read32(a_uptime)
    streak = t.read32(a_streak)
    estop = t.read8(a_estop)
    hb = [t.read32(a_hb + 4 * i) for i in range(3)]

    print(f"  s_state           = {st} ({STATES.get(st, '?')})")
    print(f"  s_fault           = {fl} ({FAULTS.get(fl, '?')})")
    print(f"  s_estop           = {estop}")
    print(f"  s_uptime_ms       = {up1} ms  ({up1 / 1000 / 60:.1f} 分钟)")
    print(f"  s_iwdg_reset_streak = {streak}")
    print(f"  s_hb_last[]       = {hb}")

    # 恢复运行，等待 1 秒，再 halt 取第二采样
    t.resume()
    time.sleep(1.0)
    t.halt()
    up2 = t.read32(a_uptime)
    tick = t.read32(sym["xTickCount"][0])
    print(f"\n  [resume 1s 后] s_uptime_ms = {up2} ms  (增量 {up2 - up1} ms)")
    print(f"  xTickCount (FreeRTOS) = {tick}")
    print(f"  判定: {'任务在跑' if up2 > up1 else '★ 停住了'}")

    print()
    print("=" * 66)
    print("  六、通信与协议计数器")
    print("=" * 66)
    ul = sym["s_stats"][0] if "s_stats" in sym else None
    # uart_link 内部静态
    for name, key in [("ul_irq_count", "ul_irq_count"), ("ul_bytes_rx", "ul_bytes_rx"),
                      ("ul_ring_overflow", "ul_ring_overflow"), ("ul_dma_err", "ul_dma_err"),
                      ("ul_ore_err", "ul_ore_err")]:
        if key in sym:
            print(f"  {name:18s} = {t.read32(sym[key][0])}")
    for name in ["vp_frames_ok", "vp_err_crc", "vp_err_field", "vp_err_range",
                 "vp_err_len", "vp_err_class", "vp_seq_gap"]:
        if name in sym:
            print(f"  {name:18s} = {t.read32(sym[name][0])}")

    print()
    print("=" * 66)
    print("  七、RTOS 堆与栈")
    print("=" * 66)
    for n in ["ucHeap", "pxCurrentTCB", "uxCurrentNumberOfTasks", "xPortSysTickHandler"]:
        if n in sym:
            print(f"  {n:24s} @ 0x{sym[n][0]:08X}  size={sym[n][1]}")
    if "pxCurrentTCB" in sym:
        tcb = t.read32(sym["pxCurrentTCB"][0])
        print(f"  pxCurrentTCB -> 0x{tcb:08X}")
        if 0x20000000 <= tcb <= 0x20020000:
            name_ptr = t.read32(tcb + 0x34)  # pcTaskName offset in TCB_t
            try:
                raw = bytes(t.read_memory_block8(name_ptr, 16))
                nm = raw.split(b"\x00")[0].decode("ascii", "replace")
                print(f"  当前任务名 = {nm!r}")
            except Exception as e:
                print(f"  读任务名失败: {e}")

    t.resume()
    session.close()
    print("\n[完成] 已恢复运行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
