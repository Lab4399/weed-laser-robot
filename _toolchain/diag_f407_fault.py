# -*- coding: utf-8 -*-
"""
diag_f407_fault.py —— 读取 F407  halted 现场的异常状态，定位卡死原因

读：IPSR/LR/PC/xPSR（核心）、SHCSR/CFSR/HFSR/DFSR（fault 状态）、
以及异常栈帧（0xFFFFFFE9/0xFFFFFFF9 压栈内容）。
"""
import sys
from pyocd.core.helpers import ConnectHelper

CORE = {
    "xPSR":  "xpsr", "LR": "lr", "PC": "pc", "SP": "sp", "MSP": "msp",
}
SYS = {
    "SHCSR":  0xE000ED24,   # 系统处理程序控制及状态
    "CFSR":   0xE000ED28,   # 可配置故障状态
    "HFSR":   0xE000ED2C,   # 硬故障状态
    "DFSR":   0xE000ED30,   # 调试故障状态
    "MMFAR":  0xE000ED34,   # MemManage 故障地址
    "BFAR":   0xE000ED38,   # BusFault 故障地址
    "AFSR":   0xE000ED3C,   # 辅助故障状态
    "NVIC_ISPR": 0xE000E200,  # 中断挂起（前 32 个 IRQ）
    "NVIC_IABR": 0xE000E300,  # 中断活跃
    "ICSR":   0xE000ED04,   # 中断控制及状态（VECTACTIVE 在低 9 位）
}
IRQ_NAMES = {  # F407 常见
    0: "WWDG", 6: "EXTI0", 7: "EXTI1", 23: "DMA1_Stream0", 27: "DMA1_Stream4",
    37: "USART1", 38: "USART2", 39: "USART3", 56: "DMA2_Stream2",
    67: "DMA2_Stream2(替代)" , 68: "ETH", 70: "OTG_FS",
}


def hexs(v):
    return f"0x{v:08X}"


def main():
    session = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f407zgtx", connect_mode="attach")
    with session:
        t = session.target
        t.halt()

        print("=== 核心寄存器 ===")
        for name, reg in CORE.items():
            try:
                print(f"  {name:5s} = {hexs(t.read_core_register(reg))}")
            except Exception as e:
                print(f"  {name:5s} = <{e}>")

        ipsr = t.read_core_register("xpsr") & 0x1FF
        print(f"\n  IPSR（当前异常号）= {ipsr}")
        if ipsr == 0:
            print("    → 线程模式（没在异常里）")
        elif ipsr == 2:
            print("    → NMI")
        elif ipsr == 3:
            print("    → **HardFault** —— 见 CFSR/HFSR")
        elif ipsr in (4, 5):
            print("    → MemManage/BusFault")
        elif ipsr == 6:
            print("    → UsageFault")
        elif ipsr == 11:
            print("    → SVC")
        elif ipsr == 14:
            print("    → PendSV")
        elif ipsr == 15:
            print("    → SysTick")
        else:
            print(f"    → 外设中断 #{ipsr-16} ({IRQ_NAMES.get(ipsr-16, '?')})")

        print("\n=== 故障状态寄存器 ===")
        shcsr = t.read32(SYS["SHCSR"])
        cfsr = t.read32(SYS["CFSR"])
        hfsr = t.read32(SYS["HFSR"])
        dfsr = t.read32(SYS["DFSR"])
        print(f"  SHCSR = {hexs(shcsr)}")
        print(f"    SVCALLPENDED   = {bool(shcsr & (1<<15))}")
        print(f"    SYSTICKACT     = {bool(shcsr & (1<<11))}")
        print(f"    PENDSVACT      = {bool(shcsr & (1<<10))}")
        print(f"    BUSFAULTACT    = {bool(shcsr & (1<<7))}")
        print(f"    MEMFAULTACT    = {bool(shcsr & (1<<4))}")
        print(f"    USGFAULTACT    = {bool(shcsr & (1<<3))}")
        print(f"    SVCALLACT      = {bool(shcsr & (1<<1))}")
        print(f"  CFSR  = {hexs(cfsr)}")
        # UFSR = cfsr[15:0]
        ufsr = cfsr & 0xFFFF
        if ufsr & (1 << 0):  print("    UFSR: UNDEFINSTR  未定义指令")
        if ufsr & (1 << 1):  print("    UFSR: INVSTATE    试图切到 ARM 状态 / 非法 EPSR")
        if ufsr & (1 << 2):  print("    UFSR: INVPC       异常返回时 PC 非法")
        if ufsr & (1 << 3):  print("    UFSR: NOCP        协处理器访问")
        if ufsr & (1 << 8):  print("    UFSR: UNALIGNED   非对齐访问")
        if ufsr & (1 << 9):  print("    UFSR: DIVBYZERO")
        bfsr = (cfsr >> 8) & 0xFF
        if bfsr & (1 << 0):  print("    BFSR: IBERR       取指总线错误")
        if bfsr & (1 << 1):  print("    BFSR: PRECISERR   精确数据总线错误")
        if bfsr & (1 << 2):  print("    BFSR: IMPRECISERR 不精确数据总线错误")
        if bfsr & (1 << 3):  print("    BFSR: UNSTKERR    出栈错误")
        if bfsr & (1 << 4):  print("    BFSR: STKERR      入栈错误")
        if bfsr & (1 << 7):  print("    BFSR: BFARVALID   BFAR 有效")
        mmfsr = (cfsr >> 16) & 0xFF
        if mmfsr & (1 << 0): print("    MMFSR: IACCVIOL   取指访问违例")
        if mmfsr & (1 << 1): print("    MMFSR: DACCVIOL   数据访问违例")
        if mmfsr & (1 << 3): print("    MMFSR: MUNSTKERR  出栈错误")
        if mmfsr & (1 << 4): print("    MMFSR: MSTKERR    入栈错误")
        if mmfsr & (1 << 7): print("    MMFSR: MMARVALID  MMFAR 有效")
        print(f"  HFSR  = {hexs(hfsr)}")
        if hfsr & (1 << 1):  print("    VECTTBL  向量表读取错误")
        if hfsr & (1 << 30): print("    FORCED   可配置故障被升级为 HardFault")
        if hfsr & (1 << 31): print("    DEBUGEVT 调试事件导致")
        if mmfsr & (1 << 7):
            print(f"  MMFAR = {hexs(t.read32(SYS['MMFAR']))}")
        if bfsr & (1 << 7):
            print(f"  BFAR  = {hexs(t.read32(SYS['BFAR']))}")

        print("\n=== NVIC ===")
        ispr = t.read32(SYS["NVIC_ISPR"])
        iabr = t.read32(SYS["NVIC_IABR"])
        icsr = t.read32(SYS["ICSR"])
        vectactive = icsr & 0xFF
        print(f"  VECTACTIVE = {vectactive}   ({'线程' if vectactive==0 else 'IRQ#'+str(vectactive-16)})")
        print(f"  ISPR = {hexs(ispr)}")
        for i in range(32):
            if ispr & (1 << i):
                print(f"    挂起: IRQ#{i} {IRQ_NAMES.get(i,'?')}")
        print(f"  IABR = {hexs(iabr)}")
        for i in range(32):
            if iabr & (1 << i):
                print(f"    活跃: IRQ#{i} {IRQ_NAMES.get(i,'?')}")

        # 异常栈帧（如果在 handler 里）
        lr = t.read_core_register("lr")
        if lr & 0xFFFFFFF8 in (0xFFFFFFF8,):
            print("\n=== 异常栈帧（LR 指示返回线程模式）===")
        if (lr & 0xFFFFFFFF) in (0xFFFFFFF9, 0xFFFFFFFD, 0xFFFFFFE9, 0xFFFFFFED):
            msp = t.read_core_register("msp")
            frame = [t.read32(msp + 4 * i) for i in range(8)]
            r0, r1, r2, r3, r12, lr_f, pc_f, xpsr_f = frame
            print(f"  R0={hexs(r0)} R1={hexs(r1)} R2={hexs(r2)} R3={hexs(r3)}")
            print(f"  R12={hexs(r12)} LR={hexs(lr_f)} PC={hexs(pc_f)} xPSR={hexs(xpsr_f)}")
            if 0x08000000 <= pc_f < 0x08100000:
                off = pc_f - 0x08000000
                print(f"  → 故障指令在 Flash 偏移 0x{off:06X}")
        t.resume()
    return 0


if __name__ == "__main__":
    sys.exit(main())
