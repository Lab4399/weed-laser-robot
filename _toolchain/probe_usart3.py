# -*- coding: utf-8 -*-
"""
probe_usart3.py —— 不改固件、不烧录，直接判断"PD8/PD9 上到底有没有接 OpenMV"

背景：
  老 GoodDog 固件走 USART3（PD8=TX / PD9=RX），新固件走 USART1（PA9/PA10）。
  实测 USART1 一个字节都收不到，但机箱里可能早就有一条接在 PD8/PD9 的线。
  若如此，只需改固件里的串口号，不必动线。

做法：
  用调试器直接配置 RCC/GPIOD/USART3（固件从不碰这三个），
  然后放手让 CPU 跑，轮询 USART3->SR。RXNE 或 ORE 一旦置位，
  就证明 PD9 上有真实的 UART 波形进来。

判读：
  收到字节 -> 线在 PD8/PD9 上，改固件端口即可
  收不到   -> 这台机器上根本没有 F407<->OpenMV 的连线（或线在 PA9/PA10 但没通）
"""
import sys
import time

from pyocd.core.helpers import ConnectHelper

RCC_AHB1ENR = 0x40023830
RCC_APB1ENR = 0x40023840
GPIOD_BASE  = 0x40020C00
USART3_BASE = 0x40004800

MODER = GPIOD_BASE + 0x00
AFR1  = GPIOD_BASE + 0x24      # PD8..PD15
PUPDR = GPIOD_BASE + 0x0C

SR = USART3_BASE + 0x00
DR = USART3_BASE + 0x04
BRR = USART3_BASE + 0x08
CR1 = USART3_BASE + 0x0C

# APB1 = 42 MHz, 115200, oversampling 16
# USARTDIV = 42e6 / (16 * 115200) = 22.7865 -> mantissa 22, fraction 13
BRR_VAL = (22 << 4) | 13


def main():
    session = ConnectHelper.session_with_chosen_probe(
        target_override='stm32f407zgtx', connect_mode='attach')
    if session is None:
        print('!! 没找到 ST-Link')
        return 1

    with session:
        t = session.target
        t.halt()

        # ---- 时钟 ----
        t.write32(RCC_AHB1ENR, t.read32(RCC_AHB1ENR) | (1 << 3))   # GPIODEN
        t.write32(RCC_APB1ENR, t.read32(RCC_APB1ENR) | (1 << 18))  # USART3EN
        time.sleep(0.02)

        # ---- PD8/PD9 -> AF7 (USART3) ----
        moder = t.read32(MODER)
        moder &= ~((0b11 << 16) | (0b11 << 18))
        moder |= ((0b10 << 16) | (0b10 << 18))
        t.write32(MODER, moder)

        afr1 = t.read32(AFR1)
        afr1 &= ~0xFF              # PD8[3:0], PD9[7:4]
        afr1 |= 0x77               # 两边都是 AF7
        t.write32(AFR1, afr1)

        # PD9 (RX) 上拉，避免悬空
        pupdr = t.read32(PUPDR)
        pupdr &= ~(0b11 << 18)
        pupdr |= (0b01 << 18)
        t.write32(PUPDR, pupdr)

        # ---- USART3: 115200 8N1, 只开接收 ----
        t.write32(BRR, BRR_VAL)
        t.write32(CR1, 0x00002004)      # UE | RE

        print(f'[配置] USART3 已开: BRR=0x{BRR_VAL:04X} CR1=0x{t.read32(CR1):08X}')
        print(f'       PD8/PD9 = AF7, PD9 上拉')

        # ---- 放开 CPU，轮询 5 秒 ----
        t.resume()
        hits = 0
        first = None
        t0 = time.time()
        while time.time() - t0 < 5.0:
            sr = t.read32(SR)
            if sr & 0x20 or sr & 0x08:      # RXNE or ORE
                hits += 1
                if first is None:
                    first = (time.time() - t0, sr, t.read32(DR))
            time.sleep(0.01)

        print(f'\n=== 结果 ===')
        print(f'  RXNE/ORE 命中次数: {hits}')
        if hits:
            dt, sr, dr = first
            print(f'  首次命中: t={dt:.2f}s  SR=0x{sr:08X}  DR=0x{dr:02X}')
            print('  判读: **PD8/PD9 上有真实 UART 数据** —— 机箱里的线接在旧端口上，')
            print('        改固件串口号即可，不需要动线。')
            rc = 0
        else:
            print('  判读: 5 秒内一个字节都没来。')
            print('        → 这台机器上 F407 与 OpenMV 之间确实没有连通，')
            print('          需要按接线表把线接到 PA9/PA10（或 PD8/PD9）。')
            rc = 2
    return rc


if __name__ == '__main__':
    sys.exit(main())
