# -*- coding: utf-8 -*-
"""读 F407 全部通信/协议计数器（只读，用已知符号地址）。"""
from pyocd.core.helpers import ConnectHelper

S_STATS = 0x20000FA0          # uart_link 5×u32
S_PROTO_STATS = 0x20000EC8 + 0x84   # vision_proto.stats
S_PROTO = 0x20000EC8
S_UPTIME = 0x2000133C
S_STREAK = 0x200018B4
S_GOOD_FRAMES = 0x20001338
S_LAST_FRAME_MS = 0x20001340
S_CRC_ERRORS = 0x20001334
S_RING_HEAD = 0x200010BA
S_RING_TAIL = 0x200010B8


def main():
    s = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f407zgtx", connect_mode="halt", exit_on_error=False)
    s.open()
    t = s.target
    t.halt()

    ul = [t.read32(S_STATS + 4 * i) for i in range(5)]
    names = ["irq_count", "bytes_rx", "ring_overflow", "dma_err", "ore_err"]
    print("=== uart_link 统计（USART1）===")
    for n, v in zip(names, ul):
        print(f"  ul_{n:14s} = {v}")

    ps = [t.read32(S_PROTO_STATS + 4 * i) for i in range(7)]
    pn = ["frames_ok", "err_crc", "err_field", "err_range", "err_len", "err_class", "seq_gap"]
    print("\n=== vision_proto 统计 ===")
    for n, v in zip(pn, ps):
        print(f"  vp_{n:14s} = {v}")

    print("\n=== 冗余计数（另一套）===")
    print(f"  s_good_frames  = {t.read32(S_GOOD_FRAMES)}")
    print(f"  s_crc_errors   = {t.read32(S_CRC_ERRORS)}")
    lf = t.read32(S_LAST_FRAME_MS)
    up = t.read32(S_UPTIME)
    print(f"  s_last_frame_ms= {lf}   uptime={up}   距上一帧 {up - lf if lf else 'N/A'} ms")
    print(f"  s_iwdg_streak  = {t.read32(S_STREAK)}")

    print("\n=== 环形缓冲 ===")
    h, tl = t.read16(S_RING_HEAD), t.read16(S_RING_TAIL)
    print(f"  head={h}  tail={tl}  存量={(h - tl) & 0xFFFF} B / 512 B")

    t.resume()
    s.close()
    print("\n[完成] 已恢复运行")


if __name__ == "__main__":
    main()
