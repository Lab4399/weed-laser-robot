# -*- coding: utf-8 -*-
"""
live_probe_f407.py —— 在线读取 FreeRTOS 调度器与安全状态，判定"卡死"发生在哪一层

判定逻辑：
  · xTickCount 不涨  -> SysTick 停了，调度器整体停摆
  · xTickCount 在涨，s_uptime_ms 不涨 -> safety 任务被永久阻塞
  · 两者都不涨 -> CPU 卡在某个死循环
"""
import sys
import time
from pyocd.core.helpers import ConnectHelper

SYM = {
    's_uptime_ms':         0x2000133C,
    's_hb_last':           0x20001318,   # uint32_t[3]
    's_fault':             0x20001346,
    's_state':             0x20001347,
    'uxSchedulerSuspended':0x200016E8,
    'xTickCount':          0x20001708,
    's_iwdg_reset_streak': 0x200018B4,
}

SYSTICK = {
    'CTRL': 0xE000E010,
    'LOAD': 0xE000E014,
    'VAL':  0xE000E018,
}

# 安全状态名（safety.h 的 sys_state_t 顺序）
STATE_NAMES = ['INIT', 'IDLE', 'AUTO', 'SAFE_STOP', 'FAULT', 'ESTOP?']

FAULT_NAMES = {
    0: 'NONE', 1: 'ESTOP', 2: 'LINK_TIMEOUT', 3: 'CRC_BURST',
    4: 'TASK_STALL', 5: 'IWDG_REPEAT', 6: 'PARAM_LOST',
    7: 'PARAM_CRC', 8: 'OVERCURRENT',
}


def main():
    session = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f407zgtx", connect_mode="attach")
    with session:
        t = session.target
        t.halt()

        def snap():
            return {
                'tick': t.read32(SYM['xTickCount']),
                'uptime': t.read32(SYM['s_uptime_ms']),
                'state': t.read8(SYM['s_state']),
                'fault': t.read8(SYM['s_fault']),
                'susp': t.read32(SYM['uxSchedulerSuspended']),
                'systick_ctrl': t.read32(SYSTICK['CTRL']),
                'systick_val': t.read32(SYSTICK['VAL']),
                'pc': t.read_core_register('pc'),
                'lr': t.read_core_register('lr'),
            }

        a = snap()
        t.resume()
        time.sleep(1.0)
        t.halt()
        b = snap()

        print("=== 两次采样（间隔 1.0s，运行态）===")
        for k in ('tick', 'uptime', 'systick_val', 'pc'):
            print(f"  {k:12s}: {a[k]:>12} -> {b[k]:>12}   {'增长' if b[k] != a[k] else '**冻结**'}")

        print("\n=== 状态 ===")
        st = b['state']
        print(f"  s_state = {st} ({STATE_NAMES[st] if st < len(STATE_NAMES) else '?'})")
        ft = b['fault']
        print(f"  s_fault = {ft} ({FAULT_NAMES.get(ft, '?')})")
        print(f"  SysTick CTRL = 0x{b['systick_ctrl']:08X} "
              f"(ENABLE={bool(b['systick_ctrl'] & 1)}, TICKINT={bool(b['systick_ctrl'] & 2)}, "
              f"CLKSOURCE={bool(b['systick_ctrl'] & 4)}, COUNTFLAG={bool(b['systick_ctrl'] & 0x10000)})")
        print(f"  uxSchedulerSuspended = {b['susp']}  ({'已挂起!' if b['susp'] else '正常'})")
        print(f"  s_iwdg_reset_streak = {t.read32(SYM['s_iwdg_reset_streak'])}")

        print("\n=== 任务心跳时间戳 s_hb_last[] ===")
        names = ['VISION', 'MOTION', 'X']
        for i in range(3):
            v = t.read32(SYM['s_hb_last'] + 4 * i)
            age = (b['uptime'] - v) & 0xFFFFFFFF
            print(f"  [{i}] {names[i]:8s} = {v:>8}   距今 {age} ms")

        print("\n=== 判读 ===")
        tick_moves = b['tick'] != a['tick']
        uptime_moves = b['uptime'] != a['uptime']
        if tick_moves and not uptime_moves:
            print("  FreeRTOS tick 正常，但 safety 任务不再运行 —— 任务被永久阻塞或已死")
        elif tick_moves and uptime_moves:
            print("  调度器与 safety 任务都在运行 —— 只是状态机停在 FAULT")
        else:
            print("  tick 也停了 —— SysTick 中断失效，调度器整体停摆")

        t.resume()
    return 0


if __name__ == '__main__':
    sys.exit(main())
