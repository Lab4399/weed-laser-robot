# -*- coding: utf-8 -*-
"""
植物病虫害识别 + 激光瞄准打击系统
链路：抓帧 -> 识别病虫害 -> 视觉伺服瞄准 -> 死区内开激光

用法：
  python main.py --sim                        # 仿真：USB 摄像头 + 打印动作
  python main.py --source leaf.jpg --sim      # 仿真：单张图片演示
  python main.py --detector blob --sim        # 无模型：颜色病斑分割
  python main.py --port COM3                  # 真机：连 Arduino 云台 + 激光
"""
import argparse
import time
import cv2
import config
from detector import build_detector
from actuator import build_actuator
from aiming import AimController


def pick_target(dets):
    """挑一个要打击的目标：非健康、置信度最高"""
    cand = [d for d in dets if d[5] in config.TARGET_CLASSES]
    if not cand:
        return None
    cand.sort(key=lambda d: -d[4])
    return cand[0]


def draw_ui(frame, dets, target, pan, tilt, aligned, laser_on):
    disp = frame.copy()
    for d in dets:
        x1, y1, x2, y2, s, c = d
        name = config.CLASS_NAMES.get(c, f"cls{c}")
        color = (0, 0, 255) if d is target else (0, 200, 0)
        cv2.rectangle(disp, (x1, y1), (x2, y2), color, 2)
        cv2.putText(disp, f"{name} {s:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cx0, cy0 = config.FRAME_W // 2, config.FRAME_H // 2
    cv2.line(disp, (cx0 - 20, cy0), (cx0 + 20, cy0), (0, 255, 255), 1)
    cv2.line(disp, (cx0, cy0 - 20), (cx0, cy0 + 20), (0, 255, 255), 1)
    if target:
        x1, y1, x2, y2, _, _ = target
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        cv2.circle(disp, (cx, cy), 5, (0, 0, 255), -1)
        cv2.line(disp, (cx0, cy0), (cx, cy), (0, 0, 255), 1)
    status = (f"pan={int(pan)} tilt={int(tilt)} "
              f"{'[已瞄准]' if aligned else '[瞄准中]'} laser={'ON' if laser_on else 'OFF'}")
    cv2.putText(disp, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return disp


def run_camera(args):
    det = build_detector(args.detector)
    act = build_actuator(sim=args.sim, port=args.port)
    aim = AimController()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("无法打开摄像头")
        act.close()
        return
    laser_on = False
    last_fire = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, (config.FRAME_W, config.FRAME_H))
            dets = det.detect(frame)
            target = pick_target(dets)
            pan, tilt, aligned = aim.pan, aim.tilt, False
            now = time.time()
            if target:
                x1, y1, x2, y2, _, _ = target
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                pan, tilt, aligned = aim.update(cx, cy)
                act.set_angles(pan, tilt)
                if aligned and now - last_fire > config.LASER_COOLDOWN_SEC:
                    act.laser(True)
                    laser_on = True
                    last_fire = now
                elif not aligned and laser_on:
                    act.laser(False)
                    laser_on = False
                if laser_on and now - last_fire > config.LASER_HOLD_SEC:
                    act.laser(False)
                    laser_on = False
            elif laser_on:
                act.laser(False)
                laser_on = False
            disp = draw_ui(frame, dets, target, pan, tilt, aligned, laser_on)
            cv2.imshow("laser strike", disp)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        act.laser(False)
        act.close()
        cap.release()
        cv2.destroyAllWindows()


def run_image(args):
    det = build_detector(args.detector)
    act = build_actuator(sim=True)
    aim = AimController()
    frame = cv2.imread(args.source)
    if frame is None:
        print(f"无法读取图片: {args.source}")
        return
    disp = cv2.resize(frame, (config.FRAME_W, config.FRAME_H))
    dets = det.detect(disp)
    target = pick_target(dets)
    if target:
        x1, y1, x2, y2, _, _ = target
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        pan, tilt, aligned = aim.update(cx, cy)
        act.set_angles(pan, tilt)
        if aligned:
            act.laser(True)
        disp = draw_ui(disp, dets, target, pan, tilt, aligned, aligned)
    else:
        disp = draw_ui(disp, dets, None, aim.pan, aim.tilt, False, False)
        print("未检测到病虫害目标")
    cv2.imshow("laser strike (image)", disp)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="0", help="0=USB摄像头 或 图片路径")
    p.add_argument("--detector", default="auto", choices=["auto", "yolo", "blob"])
    p.add_argument("--sim", action="store_true", help="仿真模式（不连串口）")
    p.add_argument("--port", default=None, help="串口，如 COM3")
    args = p.parse_args()
    if args.source == "0":
        run_camera(args)
    else:
        run_image(args)
