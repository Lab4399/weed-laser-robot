# -*- coding: utf-8 -*-
# ============================================================================
#  tracker.py —— 多目标筛选与航向误差计算
#
#  画面里同时出现多株杂草时，必须选一个作为当前作业目标，否则控制量会
#  在几个目标之间来回跳，表现为小车"抽搐"。
#
#  两件事在本文件完成：
#    1. select()   —— 从候选里选唯一目标
#    2. heading_error() —— 把目标位置换算成 F407 需要的横向误差
# ============================================================================

import config


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def select(targets):
    """
    选出唯一的作业目标。

    评分 = CONF_W * 置信度
         + AREA_W * 归一化面积        （面积大 ≈ 离得近，优先处理）
         - CENTER_W * 归一化离中心距离 （离画面中心近的更容易转到）

    返回 Target 或 None。
    """
    if not targets:
        return None

    cx_center = config.IMAGE_WIDTH * 0.5
    max_area = config.IMAGE_WIDTH * config.IMAGE_WIDTH * 0.25  # 归一化基准

    best = None
    best_score = -1e9

    for t in targets:
        if t.cls != "WEED":
            continue
        if t.conf < config.CONF_MIN_SEND:
            continue

        area_norm = _clamp(t.area / max_area, 0.0, 1.0)
        off_norm = _clamp(abs(t.cx - cx_center) / cx_center, 0.0, 1.0)

        score = (config.SELECT_CONF_W * t.conf
                 + config.SELECT_AREA_W * area_norm
                 - config.SELECT_CENTER_W * off_norm)

        if score > best_score:
            best_score = score
            best = t

    return best


def heading_error(target, img_width=None):
    """
    横向误差（像素）= 目标中心 X - 画面中心 X。

    正数代表目标在右侧（F407 应向右侧修正），负数代表在左侧。
    这个符号约定必须与 F407 的 motion.c 完全一致，否则小车会朝反方向跑。
    联调第一件事就是验证这个符号。
    """
    if target is None:
        return 0
    w = img_width or config.IMAGE_WIDTH
    return int(target.cx - (w >> 1))


class LostCounter:
    """
    连续多少帧没有有效目标。

    F407 需要区分三种状态，本类提供其中的第一种：
      目标短暂丢失（叶片被遮挡、光照突变）→ 保持当前动作，不要急停
      长时间无目标                     → 由 F407 决定减速/搜索
      链路断开                         → F407 靠帧超时判定，与本类无关
    """

    def __init__(self):
        self.frames = 0

    def update(self, target):
        if target is None:
            self.frames += 1
        else:
            self.frames = 0
        return self.frames

    @property
    def lost(self):
        return self.frames > 0
