# -*- coding: utf-8 -*-
# ============================================================================
#  detector.py —— 杂草/作物识别
#
#  两条路线，用 config.DETECTOR 切换：
#    "fomo" —— Edge Impulse 训练出的 FOMO 模型（快速 POC 路径）
#    "blob" —— 传统颜色阈值，零训练成本，用于在模型就绪前打通全链路
#
#  统一输出结构（无论底层用哪种算法）：
#      Target(cls, conf, x, y, w, h)
#  这样 tracker / protocol / main 都不需要知道底层是 FOMO 还是 blob，
#  后续把 POC 换成蒸馏压缩后的自定义模型时，只改本文件。
# ============================================================================

import config

CLS_WEED = "WEED"
CLS_CROP = "CROP"


class Target:
    __slots__ = ("cls", "conf", "x", "y", "w", "h")

    def __init__(self, cls, conf, x, y, w, h):
        self.cls = cls
        self.conf = conf
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    @property
    def cx(self):
        return self.x + (self.w >> 1)

    @property
    def cy(self):
        return self.y + (self.h >> 1)

    @property
    def area(self):
        return self.w * self.h

    def __repr__(self):
        return "<%s %.2f (%d,%d %dx%d)>" % (
            self.cls, self.conf, self.x, self.y, self.w, self.h)


class Detector:
    def __init__(self):
        self.mode = config.DETECTOR
        self._net = None
        self._labels = []
        self._blob_thresholds = []
        self.infer_count = 0
        self.infer_fail = 0

        if self.mode == "fomo":
            self._init_fomo()
        elif self.mode == "blob":
            self._init_blob()
        else:
            raise ValueError("unknown DETECTOR: %s" % self.mode)

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _init_fomo(self):
        import tf
        self._net = tf.Model(config.MODEL_PATH)
        # 标签顺序必须与训练时的 label 文件一致。
        # 顺序错了不会报错，只会把作物识别成杂草 —— 上线前必须逐类验证一次。
        self._labels = ["WEED", "CROP"]

    def _init_blob(self):
        self._blob_thresholds = []
        for name, th in config.BLOB_THRESHOLDS:
            self._blob_thresholds.append((name, th))

    # ------------------------------------------------------------------
    # 推理主入口
    # ------------------------------------------------------------------
    def detect(self, img):
        """返回 List[Target]，可能为空列表。本函数不得抛异常。"""
        self.infer_count += 1
        try:
            if self.mode == "fomo":
                return self._detect_fomo(img)
            return self._detect_blob(img)
        except Exception as e:
            # 推理失败绝不能让主循环挂掉。计入统计，本帧视为无目标。
            self.infer_fail += 1
            if config.DEBUG_PRINT:
                print("detect fail:", e)
            return []

    def _detect_fomo(self, img):
        out = []
        # tf.detect 返回 [(x, y, w, h, score, class_id), ...]
        for d in self._net.detect(img, thresholds=[(0.4, 0.4)]):
            x, y, w, h, score, cid = d
            if score < config.CONF_MIN_SEND:
                continue
            cls = self._labels[cid] if cid < len(self._labels) else CLS_WEED
            # 裁到画面内，避免边缘框越界导致下游归一化算出负数
            x = max(0, int(x)); y = max(0, int(y))
            w = min(int(w), config.IMAGE_WIDTH - x)
            out.append(Target(cls, float(score), x, y, w, int(h)))
        return out

    def _detect_blob(self, img):
        import image
        out = []
        for name, th in self._blob_thresholds:
            for b in img.find_blobs([th], pixels_threshold=120,
                                    area_threshold=120, merge=True):
                # 用填充率做一次粗筛：圆形/不规则杂草叶片的填充率低于矩形杂物
                if b.density() < 0.35:
                    continue
                # blob 没有天然置信度，用填充率归一化当代理值。
                # 这是 POC 的权宜做法，正式方案必须换成 CNN 输出。
                conf = min(0.99, 0.5 + b.density() * 0.5)
                out.append(Target(name, conf, b.x(), b.y(), b.w(), b.h()))
        return out

    # ------------------------------------------------------------------
    def stats(self):
        return (self.infer_count, self.infer_fail)
