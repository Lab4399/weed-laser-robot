# -*- coding: utf-8 -*-
"""
weeder_host.py —— 激光除杂草小车 · PC 端协作（可视化 / YOLOv8 标注 / 记录）

配合 OpenMV 端 openmv/main.py（经 UART 发 JPEG）使用：
  - 接收 OpenMV 摄像头画面
  - 用 YOLOv8（OpenCV ONNX 检测器）叠加病害/杂草标注
  - 实时显示，按 's' 截图，按 'q' 退出

串口协议（与 plant_disease_gui_openmv.py 一致）：
  [0..3] 4 字节图像长度（小端） | [4..7] 4 字节帧计数 | [8..] JPEG 数据

用法：
  python weeder_host.py --port COM5
  python weeder_host.py --port COM5 --model E:\YOLOv8_Projects\models\yolov8n.onnx
"""
import argparse
import os
import sys
import time
import struct

import cv2
import numpy as np
import serial

# 复用 YOLOv8 项目的检测器类
sys.path.append(r"E:\YOLOv8_Projects\deploy")
try:
    from yolov8_detector import YOLOv8Detector
    YOLO_OK = True
except Exception as e:
    YOLO_OK = False
    print(f"[host] 未加载 YOLOv8 检测器: {e}（仅显示原图）")


def recv_frames(ser, on_frame):
    """按协议逐帧接收 JPEG 并回调。"""
    buf = b""
    expected = None
    while True:
        if expected is None:
            if len(buf) < 4:
                buf += ser.read(4 - len(buf))
                if len(buf) < 4:
                    continue
            expected = struct.unpack("<I", buf[:4])[0]
            buf = buf[4:]
            if expected > 500_000:      # 安全上限
                buf = b""
                expected = None
                continue
        if len(buf) < expected:
            buf += ser.read(expected - len(buf))
            if len(buf) < expected:
                continue
        jpeg = buf[:expected]
        buf = buf[expected:]
        expected = None
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            on_frame(img)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True, help="OpenMV 串口号，如 COM5")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--model", default=r"E:\YOLOv8_Projects\models\yolov8n.onnx")
    p.add_argument("--conf", type=float, default=0.25)
    args = p.parse_args()

    det = None
    if YOLO_OK and os.path.exists(args.model):
        det = YOLOv8Detector(args.model, conf_thres=args.conf)
        print(f"[host] YOLOv8 加载: {args.model}")
    else:
        print("[host] 仅显示原图（无 onnx 模型；可先运行 export_onnx.py 生成）")

    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    time.sleep(2)
    print(f"[host] 已连接 {args.port}，接收 OpenMV 画面中... (q 退出 / s 截图)")

    save_dir = r"E:\PlantDiseaseProject\runs\weeder"
    os.makedirs(save_dir, exist_ok=True)
    cnt = 0

    def on_frame(img):
        nonlocal cnt
        cnt += 1
        if det is not None:
            result, boxes, scores, class_ids = det.detect(img, draw=True)
            img = result
        cv2.imshow("Weeder Host (YOLOv8)", img)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            raise StopIteration
        if k == ord("s"):
            cv2.imwrite(os.path.join(save_dir, f"frame_{cnt:05d}.jpg"), img)
            print(f"[host] 已保存截图 {cnt}")

    try:
        recv_frames(ser, on_frame)
    except (StopIteration, KeyboardInterrupt):
        pass
    finally:
        ser.close()
        cv2.destroyAllWindows()
        print("[host] 已退出")


if __name__ == "__main__":
    main()
