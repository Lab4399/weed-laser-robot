# -*- coding: utf-8 -*-
# ============================================================================
#  ranging.py —— 双目测距
#
#  公式（经典平行双目模型）：
#      Z = (f * B) / d
#      Z : 目标到相机的距离（与 f 同单位，通常为毫米）
#      f : 相机焦距，单位像素（由相机标定得到）
#      B : 双目基线，即两镜头光心间距，单位毫米
#      d : 视差，单位像素（左右图中同一物点的横坐标之差）
#
#  误差特性（决定这个模块到底能不能用）：
#      Z 与 d 成反比，所以距离越远，同样的视差误差造成的测距误差越大。
#      设 d 有 ±1 px 误差，在 Z=0.5m 处误差约 ±3cm，在 Z=2m 处误差可达 ±50cm。
#      对除草场景（工作距离 0.3~1.0m）这个精度是可用的，
#      但不要指望它能在 3m 外给出有意义的距离值。
#
#  ⚠️ 标定未完成前 STEREO_ENABLE 必须保持 False，
#     此时 dist() 返回 0，F407 侧会退化为用目标框宽 W 作为"接近程度"代理。
#     用未标定的焦距/基线算出来的距离比没有距离更危险 —— 它会看起来是正常的数字。
# ============================================================================

import config


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class StereoRanger:
    def __init__(self):
        self.enabled = bool(config.STEREO_ENABLE)
        self.f = float(config.STEREO_FOCAL_PX)
        self.b = float(config.STEREO_BASELINE_MM)
        self.valid_count = 0
        self.invalid_count = 0

        if self.enabled and (self.f <= 0 or self.b <= 0):
            # 配置自相矛盾：声称启用却没标定参数。直接拒绝启动，
            # 不要"宽容地"降级 —— 那种沉默的降级会在联调时浪费大量时间。
            raise ValueError("STEREO_ENABLE=True 但 FOCAL_PX/BASELINE_MM 未标定")

    # ------------------------------------------------------------------
    def disparity_to_mm(self, disparity_px):
        """视差（像素）→ 距离（毫米）。视差 <= 0 视为无效。"""
        if disparity_px <= 0:
            return 0
        z = (self.f * self.b) / float(disparity_px)
        z = int(z)
        if z < config.DIST_VALID_MIN_MM or z > config.DIST_VALID_MAX_MM:
            return 0
        return z

    # ------------------------------------------------------------------
    def dist(self, target, disparity_px=0):
        """
        返回目标距离（毫米）。0 表示无效。

        target        : tracker.Target 或 None
        disparity_px  : 该目标中心处的视差值，由立体匹配得到

        未启用双目、或视差无效时一律返回 0。
        """
        if target is None:
            self.invalid_count += 1
            return 0

        if not self.enabled:
            self.invalid_count += 1
            return 0

        z = self.disparity_to_mm(disparity_px)
        if z == 0:
            self.invalid_count += 1
            return 0

        self.valid_count += 1
        return z

    # ------------------------------------------------------------------
    # 单目兜底：用目标框高度作为"接近程度"的相对指标
    # ------------------------------------------------------------------
    @staticmethod
    def near_score(target, img_height):
        """
        归一化的接近程度 0.0~1.0，不需要任何标定。

        用途：在双目标定完成前，让 F407 至少能做到
        "目标看起来变大就减速"，而不是撞上去。

        原理：同一物体在画面中的成像高度与距离成反比。
        代价：不同大小的杂草给出的分数不可比，只适合做单目标场景。
        """
        if target is None or img_height <= 0 or target.h <= 0:
            return 0.0
        ratio = float(target.h) / float(img_height)   # 目标高度占画面高度的比例
        # 占画面 60% 视为"很近"，10% 视为"很远"
        return _clamp((ratio - 0.10) / (0.60 - 0.10), 0.0, 1.0)

    def stats(self):
        return (self.valid_count, self.invalid_count)
