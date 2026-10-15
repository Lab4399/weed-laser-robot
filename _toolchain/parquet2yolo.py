# -*- coding: utf-8 -*-
"""
parquet2yolo.py —— 把 HuggingFace 格式（parquet）的 crop/weed 检测集转成 YOLO 目录

数据源: Project-AgML/crop_weed_detection_latvia
        （1176 张田间图 / 7853 个框 / 2 类）
格式:   features = { image: image, objects: { bbox: [[x,y,w,h],...], categories: [int,...] } }
        HF 里 0=weed, 1=crop

输出:   E:\\PlantDiseaseProject\\datasets\\weed_yolo\\
        ├── train/images, train/labels
        ├── val/images,   val/labels
        └── data.yaml

⚠️ 类别顺序按本项目约定重新映射：  0=crop(不打)  1=weed(打击)
   与 laser_strike/config.py 的 TARGET_CLASSES=[1] 对齐。

跑法: python _toolchain\parquet2yolo.py --src E:\_data\crop_weed_latvia.parquet
"""
import argparse
import io
import os
import random
import sys

import numpy as np

PROJ = r"E:\PlantDiseaseProject"
DST = os.path.join(PROJ, r"datasets\weed_yolo")

# HF 原始标签 -> 本项目标签
HF2OURS = {0: 1, 1: 0}          # HF: 0=weed,1=crop  ->  本项目: 0=crop,1=weed
OUR_NAMES = {0: "crop", 1: "weed"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--val-ratio", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-box-px", type=float, default=4.0)
    ap.add_argument("--clean", action="store_true", help="先清空目标目录")
    args = ap.parse_args()

    import pyarrow.parquet as pq
    from PIL import Image

    if not os.path.exists(args.src):
        sys.exit(f"[conv] 找不到 {args.src}")

    print(f"[conv] 读取 {args.src}  ({os.path.getsize(args.src)/1048576:.1f} MB)")
    tbl = pq.read_table(args.src)
    print(f"[conv] 行数 {tbl.num_rows}  列 {tbl.column_names}")

    if args.clean:
        import shutil
        for sp in ("train", "val"):
            p = os.path.join(DST, sp)
            if os.path.isdir(p):
                shutil.rmtree(p)

    for sp in ("train", "val"):
        os.makedirs(os.path.join(DST, sp, "images"), exist_ok=True)
        os.makedirs(os.path.join(DST, sp, "labels"), exist_ok=True)

    img_col = tbl.column("image").to_pylist()
    obj_col = tbl.column("objects").to_pylist()

    idx = list(range(len(img_col)))
    random.Random(args.seed).shuffle(idx)
    n_val = int(round(len(idx) * args.val_ratio))
    val_set = set(idx[:n_val])

    stat = {"crop": 0, "weed": 0}
    boxes_per_img = []
    dropped = 0
    rel = []
    bad_fmt = 0

    for i, (im, ob) in enumerate(zip(img_col, obj_col)):
        if isinstance(im, dict):
            raw = im["bytes"]
        else:
            raw = im
        pil = Image.open(io.BytesIO(raw))
        pil.load()
        W, H = pil.size
        if pil.mode != "RGB":
            pil = pil.convert("RGB")

        boxes = ob.get("bbox") or []
        cats = ob.get("categories") or []

        # --- 自动判别 bbox 是绝对像素还是归一化 ---
        norm = False
        if len(boxes):
            mx = max(b[0] + b[2] for b in boxes)
            my = max(b[1] + b[3] for b in boxes)
            norm = (mx <= 1.5 and my <= 1.5)
        if norm:
            bad_fmt += 1

        lines = []
        for b, c in zip(boxes, cats):
            if norm:
                cx, cy, bw, bh = b[0], b[1], b[2], b[3]
            else:
                x, y, w, h = b[0], b[1], b[2], b[3]
                if w < args.min_box_px or h < args.min_box_px:
                    dropped += 1
                    continue
                cx, cy, bw, bh = (x + w / 2) / W, (y + h / 2) / H, w / W, h / H
            cc = int(c)
            if cc not in HF2OURS:
                continue
            cc = HF2OURS[cc]
            cx = min(max(cx, 0.0), 1.0)
            cy = min(max(cy, 0.0), 1.0)
            bw = min(max(bw, 0.0), 1.0)
            bh = min(max(bh, 0.0), 1.0)
            if bw <= 0 or bh <= 0:
                dropped += 1
                continue
            lines.append(f"{cc} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            stat[OUR_NAMES[cc]] += 1
            rel.append(np.sqrt(bw * bh))

        if not lines:
            continue

        sp = "val" if i in val_set else "train"
        stem = f"latvia_{i:05d}"
        pil.save(os.path.join(DST, sp, "images", stem + ".jpg"), quality=95)
        with open(os.path.join(DST, sp, "labels", stem + ".txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        boxes_per_img.append(len(lines))

    print(f"\n[conv] 完成 -> {DST}")
    print(f"  类别框数      : crop(作物)={stat['crop']}  weed(杂草)={stat['weed']}")
    print(f"  每图平均框数  : {np.mean(boxes_per_img):.1f}  (最多 {max(boxes_per_img)})")
    print(f"  目标相对尺寸  : 中位 {np.median(rel):.4f}  均值 {np.mean(rel):.4f}  "
          f"最小 {np.min(rel):.4f} 最大 {np.max(rel):.4f}")
    if rel:
        small = sum(1 for r in rel if np.sqrt(r) < 32 / 640)
        print(f"  小目标(<32px@640): {small} 个 ({small/len(rel)*100:.1f}%)")
    print(f"  丢弃过小框    : {dropped}")
    if bad_fmt:
        print(f"  ⚠ 有 {bad_fmt} 张的框看起来是归一化坐标（非像素），已按归一化处理")

    for sp in ("train", "val"):
        ni = len(os.listdir(os.path.join(DST, sp, "images")))
        nl = len(os.listdir(os.path.join(DST, sp, "labels")))
        print(f"  {sp:5s}: {ni} 图 / {nl} 标注  {'OK' if ni == nl else '✗ 数量不匹配!'}")
    print(f"\n  数据配置: {os.path.join(DST, 'data.yaml')}")
    print("  下一步  : python train_weed.py --data "
          + os.path.join(DST, "data.yaml") + " --epochs 100")


if __name__ == "__main__":
    main()
