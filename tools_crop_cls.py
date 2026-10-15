# -*- coding: utf-8 -*-
"""从 weed_yolo 检测标注裁剪 crop/weed 贴片 -> 96x96 分类数据集 weed_cls"""
import os, glob
import cv2
import numpy as np

SRC = r'E:\PlantDiseaseProject\datasets\weed_yolo'
DST = r'E:\PlantDiseaseProject\datasets\weed_cls'
SZ = 96
CLS = {0: 'crop', 1: 'weed'}

total = {0: 0, 1: 0}
for split in ('train', 'val'):
    imgs = sorted(glob.glob(os.path.join(SRC, split, 'images', '*.jpg')))
    for ip in imgs:
        lb = ip.replace('images', 'labels')[:-4] + '.txt'
        if not os.path.exists(lb):
            continue
        img = cv2.imread(ip)
        h, w = img.shape[:2]
        with open(lb) as f:
            for line in f:
                p = line.split()
                if len(p) < 5:
                    continue
                c = int(p[0]); x, y, bw, bh = map(float, p[1:5])
                x1 = int((x - bw / 2) * w); y1 = int((y - bh / 2) * h)
                x2 = int((x + bw / 2) * w); y2 = int((y + bh / 2) * h)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 - x1 < 8 or y2 - y1 < 8:
                    continue
                crop = img[y1:y2, x1:x2]
                crop = cv2.resize(crop, (SZ, SZ), interpolation=cv2.INTER_AREA)
                d = os.path.join(DST, split, CLS[c])
                os.makedirs(d, exist_ok=True)
                fn = os.path.join(d, f'{os.path.basename(ip)[:-4]}_{x1}_{y1}.jpg')
                cv2.imwrite(fn, crop)
                total[c] += 1
print('patches:', total)
for split in ('train', 'val'):
    for c in (0, 1):
        d = os.path.join(DST, split, CLS[c])
        print(split, CLS[c], len(glob.glob(os.path.join(d, '*.jpg'))))
