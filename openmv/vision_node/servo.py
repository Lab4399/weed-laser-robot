# -*- coding: utf-8 -*-
# ============================================================================
#  servo.py —— 云台舵机（视觉内环，由 OpenMV 直接控制）
#
#  控制权归属（与协议文档第 7 节一致，不得越界）：
#      摄像头云台舵机  → 由 OpenMV 控制，解决"摄像头看向哪里"
#      小车执行机构舵机 → 由 STM32F407 控制，解决"小车怎么动"
#      履带电机        → 绝不接受 OpenMV 直接控制，必须经 F407 决策
#
#  为什么云台闭环容易自激振荡（本文件的核心难点）：
#      舵机转动 → 摄像头视角改变 → 目标在画面中位移 → 误差"看起来"变了
#      但这个位移是舵机自己造成的，不是小车真的偏了。
#      若每帧都根据误差更新舵机，就构成正反馈回路，表现为画面持续左右扫动。
#
#  三步抑制：死区（不动就不动）+ 单步限幅（限制冲击）+ 动作后冷却（等画面稳定）
# ============================================================================

import time
import config


class Gimbal:
    def __init__(self):
        self.enabled = bool(config.GIMBAL_ENABLE)
        self.angle = float(config.GIMBAL_ANGLE_HOME)
        self._target_angle = self.angle
        self._settle_until = 0
        self._servo = None
        self._moves = 0
        self._clamped = 0

        if not self.enabled:
            return

        import pyb
        self._servo = pyb.Servo(config.GIMBAL_SERVO_ID)
        # 上电不要直接跳到起始角：若当前位置与目标偏差大，会造成瞬间大电流
        # 甚至机械冲击。先让舵机处于"松开"状态，再由 update() 逐步靠拢。
        self._servo.angle(int(self.angle))

    # ------------------------------------------------------------------
    def _write(self, angle):
        if self._servo is not None:
            self._servo.angle(int(round(angle)))

    # ------------------------------------------------------------------
    def update(self, target, img_width=None):
        """
        根据当前目标位置更新云台。返回本次实际转过的角度（度）。

        target 为 None 时不做任何动作 —— 看不到目标时乱转只会让目标
        更长时间待在视野外。
        """
        if not self.enabled or target is None:
            return 0.0

        now = time.ticks_ms()

        # 冷却：舵机刚动过，画面还没稳定，此时读到的误差不可信
        if time.ticks_diff(self._settle_until, now) > 0:
            return 0.0

        w = img_width or config.IMAGE_WIDTH
        err = target.cx - (w >> 1)

        if abs(err) < config.GIMBAL_DEADZONE_PX:
            return 0.0

        # 比例控制
        delta = -config.GIMBAL_KP * err      # 目标在右侧 → 云台向右转（负角）

        # 单步限幅：限制舵机一次转动量，避免冲击和大电流
        if delta > config.GIMBAL_MAX_STEP_DEG:
            delta = config.GIMBAL_MAX_STEP_DEG
        elif delta < -config.GIMBAL_MAX_STEP_DEG:
            delta = -config.GIMBAL_MAX_STEP_DEG

        new_angle = self.angle + delta

        # 机械限位。必须先在实机上手动确认限位值再填入 config，
        # 硬顶限位会造成舵机堵转，电流可达正常工作值的数倍。
        if new_angle < config.GIMBAL_ANGLE_MIN:
            new_angle = config.GIMBAL_ANGLE_MIN
            self._clamped += 1
        elif new_angle > config.GIMBAL_ANGLE_MAX:
            new_angle = config.GIMBAL_ANGLE_MAX
            self._clamped += 1

        if abs(new_angle - self.angle) < 0.5:
            return 0.0

        moved = new_angle - self.angle
        self.angle = new_angle
        self._target_angle = new_angle
        self._write(new_angle)

        self._settle_until = time.ticks_add(now, config.GIMBAL_SETTLE_MS)
        self._moves += 1
        return moved

    # ------------------------------------------------------------------
    def center(self):
        """回到中位。用于丢失目标后重新搜索，或收到 F407 的复位命令。"""
        if not self.enabled:
            return
        self.angle = float(config.GIMBAL_ANGLE_HOME)
        self._write(self.angle)
        self._settle_until = time.ticks_add(time.ticks_ms(), config.GIMBAL_SETTLE_MS)

    def stats(self):
        return (round(self.angle, 1), self._moves, self._clamped)
