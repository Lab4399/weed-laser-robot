# -*- coding: utf-8 -*-
"""瞄准：视觉伺服。根据目标框中心与图像中心的像素误差，输出云台角度。"""
import config


class AimController:
    def __init__(self):
        self.pan = config.PAN_INIT
        self.tilt = config.TILT_INIT

    def update(self, cx, cy):
        """输入目标像素中心，返回 (pan, tilt, aligned: bool)"""
        ex = cx - config.FRAME_W / 2.0   # 水平误差：>0 目标偏右
        ey = cy - config.FRAME_H / 2.0   # 垂直误差：>0 目标偏下
        aligned = abs(ex) <= config.DEADZONE_PX and abs(ey) <= config.DEADZONE_PX
        if not aligned:
            dp = config.KP_PAN * ex
            dt = config.KP_TILT * ey
            dp = max(-config.MAX_STEP_DEG, min(config.MAX_STEP_DEG, dp))
            dt = max(-config.MAX_STEP_DEG, min(config.MAX_STEP_DEG, dt))
            self.pan += dp
            self.tilt += dt
        self.pan = max(config.PAN_MIN, min(config.PAN_MAX, self.pan))
        self.tilt = max(config.TILT_MIN, min(config.TILT_MAX, self.tilt))
        return self.pan, self.tilt, aligned

    def reset(self):
        self.pan = config.PAN_INIT
        self.tilt = config.TILT_INIT
