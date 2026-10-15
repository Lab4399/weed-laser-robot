# -*- coding: utf-8 -*-
"""Crop-Weed2 PascalVOC -> YOLO 目录(weed_yolo) 转换"""
import os, glob, random, shutil
import xml.etree.ElementTree as ET

SRC = r'E:\PlantDiseaseProject\datasets\_cw2_ext\Object-detection-Dataset-Crop-Weed2-master'
DST = r'E:\PlantDiseaseProject\datasets\weed_yolo'

xmls = sorted(glob.glob(os.path.join(SRC, '**', '*.xml'), recursive=True))
# 类别收集
classes = []
for x in xmls:
    root = ET.parse(x).getroot()
    for o in root.findall('.//object'):
        n = o.findtext('name').strip()
        if n not in classes:
            classes.append(n)
cls2id = {c: i for i, c in enumerate(classes)}
print('classes:', classes)

random.seed(0)
random.shuffle(xmls)
nval = max(1, int(len(xmls) * 0.15))
val_x, train_x = xmls[:nval], xmls[nval:]
print(f'total={len(xmls)} train={len(train_x)} val={len(val_x)}')


def conv(xml_path, out_set, idx):
    """解析 xml，拷贝 jpg 为新名 idx.jpg，写 label txt"""
    root = ET.parse(xml_path).getroot()
    jpg = xml_path[:-4] + '.jpg'
    w = int(root.findtext('.//size/width'))
    h = int(root.findtext('.//size/height'))
    lines = []
    for o in root.findall('.//object'):
        c = cls2id[o.findtext('name').strip()]
        b = o.find('bndbox')
        x1 = float(b.findtext('xmin')); y1 = float(b.findtext('ymin'))
        x2 = float(b.findtext('xmax')); y2 = float(b.findtext('ymax'))
        xc = ((x1 + x2) / 2) / w; yc = ((y1 + y2) / 2) / h
        bw = (x2 - x1) / w; bh = (y2 - y1) / h
        xc = min(0.999999, max(0.000001, xc)); yc = min(0.999999, max(0.000001, yc))
        bw = min(0.999999, max(0.000001, bw)); bh = min(0.999999, max(0.000001, bh))
        lines.append(f'{c} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}')
    img_dir = os.path.join(DST, out_set, 'images'); os.makedirs(img_dir, exist_ok=True)
    lbl_dir = os.path.join(DST, out_set, 'labels'); os.makedirs(lbl_dir, exist_ok=True)
    new_img = os.path.join(img_dir, f'{idx}.jpg')
    if not os.path.exists(new_img):
        shutil.copy(jpg, new_img)
    with open(os.path.join(lbl_dir, f'{idx}.txt'), 'w') as f:
        f.write('\n'.join(lines))
    return len(lines)


cnt = 0
for x in train_x:
    cnt += 1
    conv(x, 'train', cnt)
for x in val_x:
    cnt += 1
    conv(x, 'val', cnt)

yaml_path = os.path.join(DST, 'data.yaml')
with open(yaml_path, 'w', encoding='utf-8') as f:
    f.write(f"path: {DST}\n")
    f.write('train: train/images\n')
    f.write('val: val/images\n\n')
    f.write(f"nc: {len(classes)}\n")
    f.write('names:\n')
    for i, c in enumerate(classes):
        f.write(f"  {i}: {c}\n")
print('wrote', yaml_path)
print('labels classes count done')
