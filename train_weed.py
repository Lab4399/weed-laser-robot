# -*- coding: utf-8 -*-
"""
杂草检测 YOLO 训练 —— 为 laser_strike 打击闭环训练专用杂草模型
用法(用 venv 的 python):
  E:\\PlantDiseaseProject\\venv\\Scripts\\python.exe train_weed.py --data <data.yaml> [--epochs 100 --batch 8]
产出: models\\weed_det\\weights\\best.pt -> 自动复制为 models\\best.pt (laser_strike config.MODEL_PATH)
数据约定: YOLO 格式  datasets\\weed_yolo\\{train,val}\\{images,labels} + data.yaml
"""
import os
import sys
import shutil
import argparse

sys.stdout.reconfigure(encoding='utf-8')
from ultralytics import YOLO

OUT_DIR = r'E:\PlantDiseaseProject\models'


def main():
    ap = argparse.ArgumentParser(description='杂草检测训练')
    ap.add_argument('--data', default=r'E:\PlantDiseaseProject\datasets\weed_yolo\data.yaml')
    ap.add_argument('--model', default='yolov8n.pt')
    ap.add_argument('--epochs', type=int, default=100)
    ap.add_argument('--batch', type=int, default=8)
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--name', default='weed_det')
    ap.add_argument('--workers', type=int, default=0)
    args = ap.parse_args()

    if not os.path.exists(args.data):
        sys.exit(f'[train] 找不到数据配置: {args.data}\n'
                 f'请放置数据集并生成 data.yaml，目录约定：\n'
                 f'  datasets/weed_yolo/train/images|labels, val/images|labels\n'
                 f'  data.yaml 含 path/train/val/nc/names\n'
                 f'下载指引见桌面《两条线汇总训练方案.md》与 README 命令。')

    m = YOLO(args.model)
    print('[train] 数据配置:', args.data)
    m.train(data=args.data, epochs=args.epochs, batch=args.batch, imgsz=args.imgsz,
            project=OUT_DIR, name=args.name, device=0, workers=args.workers,
            plots=True, verbose=True)

    best_src = os.path.join(OUT_DIR, args.name, 'weights', 'best.pt')
    dst = r'E:\PlantDiseaseProject\models\best.pt'
    if os.path.exists(best_src):
        shutil.copy(best_src, dst)
        print('[train] 已就位 laser_strike 加载路径:', dst)
    print('[train] 完成。下一步: cd E:\\PlantDiseaseProject\\laser_strike && python main.py --sim '
          '或真机 python main.py --port COM3')


if __name__ == '__main__':
    main()
