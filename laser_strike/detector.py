# -*- coding: utf-8 -*-
"""病虫害识别：YOLOv8（专用模型 + 通用兜底） 或 颜色病斑分割（无模型兜底）"""
import os
import cv2
import numpy as np
import config


class BaseDetector:
    def detect(self, frame):
        """返回 [(x1, y1, x2, y2, score, class_id), ...]，可能为空列表"""
        raise NotImplementedError


class YoloDetector(BaseDetector):
    """YOLOv8 检测：优先专用病虫害模型，缺失则回退通用模型（演示闭环）"""

    def __init__(self, model_path=None):
        from ultralytics import YOLO
        path = model_path or config.MODEL_PATH
        if not os.path.exists(path):
            if os.path.exists(config.FALLBACK_MODEL):
                path = config.FALLBACK_MODEL
                print(f"[detector] 专用模型不存在，回退通用模型: {path}")
            else:
                raise FileNotFoundError(f"模型不存在: {config.MODEL_PATH}")
        print(f"[detector] 加载 YOLO 模型: {path}")
        self.model = YOLO(path)

    def detect(self, frame, conf=config.CONF_THRES):
        r = self.model(frame, conf=conf, iou=config.IOU_THRES,
                       imgsz=config.IMG_SIZE, verbose=False)[0]
        out = []
        if r.boxes is not None and len(r.boxes) > 0:
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            cls = r.boxes.cls.cpu().numpy().astype(int)
            for b, s, c in zip(xyxy, confs, cls):
                x1, y1, x2, y2 = map(int, b)
                out.append((x1, y1, x2, y2, float(s), int(c)))
        return out


class BlobDetector(BaseDetector):
    """颜色病斑分割（无模型时的兜底）：检测褐/黄/白病斑，返回面积最大的若干斑块框。

    植物病害常表现为叶面褐斑、黄斑、白粉。用 HSV 阈值定位病斑，
    让系统在没有训练模型时也能演示完整的"识别->瞄准->激光"闭环。
    """

    def __init__(self):
        self.lower1 = np.array([8, 50, 40])    # 褐色病斑
        self.upper1 = np.array([25, 255, 200])
        self.lower2 = np.array([20, 60, 100])  # 黄色病斑
        self.upper2 = np.array([35, 255, 255])
        self.lower3 = np.array([0, 0, 180])    # 白色粉斑
        self.upper3 = np.array([180, 40, 255])

    def detect(self, frame, conf=0):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        m1 = cv2.inRange(hsv, self.lower1, self.upper1)
        m2 = cv2.inRange(hsv, self.lower2, self.upper2)
        m3 = cv2.inRange(hsv, self.lower3, self.upper3)
        mask = cv2.bitwise_or(cv2.bitwise_or(m1, m2), m3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in contours:
            if cv2.contourArea(c) < 200:  # 过滤噪声
                continue
            x, y, w, h = cv2.boundingRect(c)
            out.append((x, y, x + w, y + h, 1.0, 0))  # class_id=0 表示"病斑"
        out.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
        return out[:3]


def build_detector(name="auto"):
    """auto: 优先 YOLO，失败回退颜色病斑分割"""
    if name == "blob":
        return BlobDetector()
    if name == "yolo":
        return YoloDetector()
    try:
        return YoloDetector()
    except Exception as e:
        print(f"[detector] YOLO 不可用({e})，回退颜色病斑分割")
        return BlobDetector()
