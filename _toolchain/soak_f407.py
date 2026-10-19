# -*- coding: utf-8 -*-
"""
soak_f407.py —— 脱机生存测试

目的：回答"拔掉调试器之后，这台机器能不能自己一直跑"。
做法：清掉 .noinit 里的连续复位计数 → 复位 → **断开调试器** → 静置 N 秒
      → 重新连上读 uptime / tick / 状态。

判读依据（三选一，必须能区分开）：
  · uptime ≈ N×1000 且 streak=0        -> 固件健康，能脱机独立运行
  · uptime 只有几百毫秒、streak 在涨     -> 看门狗复位环，仍在重启
  · uptime 不涨但 tick 在涨             -> 调度器活着，safety 任务被阻塞
"""
import sys
import time

from pyocd.core.helpers import ConnectHelper

ADDR = {
    's_uptime_ms':   0x2000133C,
    's_state':       0x20001347,
    's_fault':       0x20001346,
    's_hb_last':     0x20001318,
    'xTickCount':    0x20001708,
    'streak':        0x200018B4,
}
STATE_NAME = {0: 'INIT', 1: 'IDLE', 2: 'AUTO', 3: 'SAFE_STOP', 4: 'FAULT'}
FAULT_NAME = {0: 'NONE', 1: 'LINK_TIMEOUT', 2: 'CRC_BURST', 3: 'ESTOP',
              4: 'TASK_STALL', 5: 'PARAM_LOST', 6: 'IWDG_REPEAT',
              7: 'MOTOR_DISABLED'}


def connect():
    return ConnectHelper.session_with_chosen_probe(
        target_override='stm32f407zgtx', connect_mode='attach')


def main():
    hold_s = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

    # ---------- 阶段 1：清零计数、复位、断开 ----------
    session = connect()
    if session is None:
        print('!! 没找到 ST-Link')
        return 1
    with session:
        t = session.target
        t.halt()
        # 调试期间冻结 IWDG，避免 halt 本身触发复位污染结论
        t.write32(0xE0042004, t.read32(0xE0042004) | 0x100)
        t.write32(ADDR['streak'], 0)
        print(f"[准备] streak 已清零 -> {t.read32(ADDR['streak'])}")
        t.reset()
        t.resume()
    print('[断开] 调试器已释放，固件开始独立运行')
    print(f'[等待] 静置 {hold_s:.0f} 秒……')

    time.sleep(hold_s)

    # ---------- 阶段 2：重新连上验收 ----------
    session = connect()
    if session is None:
        print('!! 重新连接失败')
        return 1
    with session:
        t = session.target
        t.halt()
        up1 = t.read32(ADDR['s_uptime_ms'])
        tk1 = t.read32(ADDR['xTickCount'])
        t.resume()
        time.sleep(0.5)
        t.halt()
        up2 = t.read32(ADDR['s_uptime_ms'])
        tk2 = t.read32(ADDR['xTickCount'])
        st = t.read8(ADDR['s_state'])
        ft = t.read8(ADDR['s_fault'])
        streak = t.read32(ADDR['streak'])
        hb = [t.read32(ADDR['s_hb_last'] + 4 * i) for i in range(3)]

        print('\n=== 脱机运行结果 ===')
        print(f'  uptime : {up1} -> {up2} ms      (期望 ≥ {int(hold_s*1000*0.9)}；'
              f'{"持续在跑" if up2 > up1 else "**冻结**"})')
        print(f'  tick   : {tk1} -> {tk2}')
        print(f'  state  : {st} ({STATE_NAME.get(st, "?")})')
        print(f'  fault  : {ft} ({FAULT_NAME.get(ft, "?")})')
        print(f'  streak : {streak}')
        print(f'  hb[VISION/CONTROL/MOTION] = {hb}')

        print('\n=== 判读 ===')
        expect = hold_s * 1000 * 0.8
        if up2 > expect and streak == 0 and st in (1, 2):
            print(f'  PASS —— 脱机独立运行 {up2/1000:.1f}s 无复位，可以上电池。')
            rc = 0
        elif up2 < 2000:
            print(f'  FAIL —— 只跑了 {up2} ms，看门狗仍在反复复位（streak={streak}）。')
            rc = 2
        elif up2 <= up1:
            print('  FAIL —— uptime 冻结，safety 任务没有在跑。')
            rc = 3
        else:
            print(f'  WARN —— 在跑但状态异常: state={STATE_NAME.get(st)} fault={FAULT_NAME.get(ft)}')
            rc = 4
        t.resume()
    return rc


if __name__ == '__main__':
    sys.exit(main())
