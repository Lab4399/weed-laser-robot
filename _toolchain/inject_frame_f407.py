# -*- coding: utf-8 -*-
"""
inject_frame_f407.py —— 绕过物理层，把一帧直接注入 F407 的环形缓冲

用途：在 F407 与 OpenMV 还没接线时，单独验证
      「协议解析 → 目标发布 → 安全模块计数」这一段是不是通的。

做法：halt 住 CPU（此时无并发），把字节写进 uart_link 的 s_ring，
      按驱动的方式推进 s_ring_head，再 resume。
      视觉任务随后会像收到真实串口数据一样把它读走、解析、计数。

判据：
      vp_frames_ok +1 且 vp_err_crc 不变  -> 接收链路完全正常，只差一根线
      vp_frames_ok 不变                    -> 解析/任务有问题，接线也没用
"""
import sys
import time

from pyocd.core.helpers import ConnectHelper

S_PROTO   = 0x20000EC8
S_RING    = 0x200010BC
S_RING_SZ = 0x200
HEAD_ADDR = 0x200010BA
TAIL_ADDR = 0x200010B8

# s_proto 内各计数的偏移（与 verify_f407.py 用的是同一套，已实测核对）
OFF = {
    'frames_ok':  0x20000F4C - S_PROTO,
    'err_crc':    0x20000F50 - S_PROTO,
    'err_field':  0x20000F54 - S_PROTO,
    'err_range':  0x20000F58 - S_PROTO,
    'err_len':    0x20000F5C - S_PROTO,
    'err_class':  0x20000F60 - S_PROTO,
    'seq_gap':    0x20000F64 - S_PROTO,
}

# 交付包 uart_protocol.py 的测试向量之一，CRC 已用 Python 与 C 双向验证
FRAME = b"@T,104,WEED,0.88,52,131,60,71,0*6C\n"


def main():
    session = ConnectHelper.session_with_chosen_probe(
        target_override='stm32f407zgtx', connect_mode='attach')
    if session is None:
        print('!! 没找到 ST-Link')
        return 1

    with session:
        t = session.target
        t.halt()

        def stats():
            base = t.read32(S_PROTO)
            out = {'raw0': base}
            for k, off in OFF.items():
                out[k] = t.read32(S_PROTO + off)
            return out

        before = stats()
        head = t.read16(HEAD_ADDR)
        tail = t.read16(TAIL_ADDR)
        print(f'[注入前] frames_ok={before["frames_ok"]} err_crc={before["err_crc"]} '
              f'head={head} tail={tail}')

        # 环形缓冲写入（按驱动同样的掩码规则）
        pos = head
        for b in FRAME:
            t.write8(S_RING + pos, b)
            pos = (pos + 1) & (S_RING_SZ - 1)
        t.write16(HEAD_ADDR, pos)
        print(f'[注入] {len(FRAME)} 字节: {FRAME!r}')
        print(f'       head {head} -> {pos}')

        t.resume()
        time.sleep(0.3)          # 视觉任务 5ms 轮询，足够跑完
        t.halt()
        after = stats()
        print(f'[注入后] frames_ok={after["frames_ok"]} err_crc={after["err_crc"]} '
              f'err_field={after["err_field"]} err_range={after["err_range"]}')

        d = after['frames_ok'] - before['frames_ok']
        print('\n=== 判读 ===')
        if d == 1:
            print('  PASS —— 帧被完整接收并解析。')
            print('          F407 侧从环形缓冲到目标发布的整条链是通的，')
            print('          剩下的唯一缺口就是 PD/PA 之间那两根线。')
            rc = 0
        elif d == 0:
            print('  FAIL —— 帧没有被接受。看 err_crc/err_field 变化：')
            print('          若 err_crc 增加，是校验/帧格式问题；')
            print('          若都不变，是视觉任务没有从 ring 里取数据。')
            rc = 2
        else:
            print(f'  !! frames_ok 增加了 {d}，异常（一帧只应计一次）')
            rc = 3
        t.resume()
    return rc


if __name__ == '__main__':
    sys.exit(main())
