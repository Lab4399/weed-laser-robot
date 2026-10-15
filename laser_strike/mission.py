# -*- coding: utf-8 -*-
"""
一套完整动作：行走 -> 识别 -> 发射 -> 完成

  [1/4] 行走   GOOD DOG 前进
  [2/4] 识别   边前进边检测病虫害（YOLO 或 颜色病斑），发现即停
  [3/4] 发射   停止行走，激光开启 N 秒
  [4/4] 完成   关激光、急停、收尾

用法：
  python mission.py --sim                   # 全仿真：打印动作 + USB 摄像头识别
  python mission.py --sim --source a.jpg    # 仿真：用一张图片做识别
  python mission.py --detector blob --sim   # 无模型：颜色病斑分割
  python mission.py --dog-port COM4 --laser-port COM3   # 真机：GOOD DOG + 激光云台
"""
import argparse
import time
import cv2
import config
from detector import build_detector
from actuator import build_actuator
from gooddog import build_dog


def pick_target(dets):
    """挑一个要打击的目标：非健康、置信度最高"""
    cand = [d for d in dets if d[5] in config.TARGET_CLASSES]
    if not cand:
        return None
    cand.sort(key=lambda d: -d[4])
    return cand[0]


def draw_detect(frame, dets, target):
    disp = frame.copy()
    for d in dets:
        x1, y1, x2, y2, s, c = d
        name = config.CLASS_NAMES.get(c, f"cls{c}")
        color = (0, 0, 255) if d is target else (0, 200, 0)
        cv2.rectangle(disp, (x1, y1), (x2, y2), color, 2)
        cv2.putText(disp, f"{name} {s:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return disp


def run_mission(args):
    det = build_detector(args.detector)
    dog = build_dog(sim=args.sim, port=args.dog_port)
    act = build_actuator(sim=args.sim, port=args.laser_port)

    try:
        # ===== [1/4] 行走 =====
        print("\n[1/4] 行走：机器狗前进")
        dog.move(config.DOG_FORWARD_SPEED)

        # ===== [2/4] 识别 =====
        print("[2/4] 识别：检测病虫害中...")
        target = None
        cap = None
        if args.source:
            frame = cv2.imread(args.source)
            if frame is None:
                print(f"  无法读取图片 {args.source}，视为未发现目标")
            else:
                frame = cv2.resize(frame, (config.FRAME_W, config.FRAME_H))
                dets = det.detect(frame)
                target = pick_target(dets)
                cv2.imshow("mission", draw_detect(frame, dets, target))
                cv2.waitKey(500)
        else:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("  无法打开摄像头")
                if args.sim:
                    print("  仿真模式：模拟发现目标")
                    target = (0, 0, 10, 10, 1.0, 0)  # 占位目标
                    time.sleep(1)
            else:
                start = time.time()
                while time.time() - start < config.SCAN_TIMEOUT_SEC:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    frame = cv2.resize(frame, (config.FRAME_W, config.FRAME_H))
                    dets = det.detect(frame)
                    target = pick_target(dets)
                    cv2.imshow("mission", draw_detect(frame, dets, target))
                    if target:
                        name = config.CLASS_NAMES.get(target[5], f"cls{target[5]}")
                        print(f"  发现目标：{name}")
                        break
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                cap.release()

        # ===== [3/4] 发射 =====
        dog.stop()
        if target:
            print(f"[3/4] 发射：停下 + 激光开启 {config.LASER_HOLD_SEC}s")
            act.laser(True)
            time.sleep(config.LASER_HOLD_SEC)
            act.laser(False)
        else:
            print("[3/4] 未发现目标，跳过发射")

        # ===== [4/4] 完成 =====
        print("[4/4] 完成：关激光 + 急停")
        dog.stop()
        act.estop()
    finally:
        dog.close()
        act.close()
        cv2.destroyAllWindows()
        print("动作序列结束")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--sim", action="store_true", help="仿真模式（不连硬件）")
    p.add_argument("--source", default=None, help="用单张图片做识别（可选）")
    p.add_argument("--detector", default="auto", choices=["auto", "yolo", "blob"])
    p.add_argument("--dog-port", default=None, help="GOOD DOG 串口，如 COM4")
    p.add_argument("--laser-port", default=None, help="激光云台串口，如 COM3")
    args = p.parse_args()
    run_mission(args)
