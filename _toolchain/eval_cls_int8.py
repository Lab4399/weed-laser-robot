# -*- coding: utf-8 -*-
r"""
eval_cls_int8.py —— int8 分类模型的逐类评估

原train_cls_int8.py 只打印总体 accuracy，在 crop:weed = 17:1 的失衡数据上
看不出问题（总体准确率 94% 也可能意味着 crop 全判成 weed）。这个脚本按类
输出混淆矩阵，并给出两个方向的错误率：

  crop误判为 weed  = 误打作物（激光打错目标）
  weed 误判为 crop  = 漏打杂草

跑法:
  python _toolchain\eval_cls_int8.py --model models\weed_cls_int8.tflite
  python _toolchain\eval_cls_int8.py --model <a.tflite> --compare <b.tflite>
"""
import argparse
import glob
import os

import numpy as np

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf  # noqa: E402

PROJ = r"E:\PlantDiseaseProject"
BASE = os.path.join(PROJ, r"datasets\weed_cls")
SZ = 96
CLS = ["crop", "weed"]


def load_split(sp, sz):
    xs, ys = [], []
    for c, name in enumerate(CLS):
        for f in sorted(glob.glob(os.path.join(BASE, sp, name, "*.jpg"))):
            img = tf.image.decode_jpeg(tf.io.read_file(f), channels=1)
            img = tf.image.resize(img, [sz, sz])
            xs.append(tf.cast(img, tf.float32) - 128.0)
            ys.append(c)
    return tf.stack(xs).numpy().astype(np.float32), np.array(ys, np.int32)


def input_size(model_path):
    import tensorflow as _tf
    it = _tf.lite.Interpreter(model_path=model_path)
    return int(it.get_input_details()[0]['shape'][1])


def predict(model_path, x):
    it = tf.lite.Interpreter(model_path=model_path)
    it.allocate_tensors()
    ind = it.get_input_details()[0]
    outd = it.get_output_details()[0]
    # 输入尺寸由模型自身决定（48x48 的 C8T6 版 / 96x96 的通用版）
    sz = int(ind['shape'][1])
    assert x.shape[1] == sz, f"模型期望 {sz}x{sz}，但验证集是 {x.shape[1]}"
    isz, izp = ind['quantization'][0], ind['quantization'][1]
    osz, ozp = outd['quantization'][0], outd['quantization'][1]
    preds = np.empty(len(x), np.int32)
    # 该模型输入维度固化为 [1,H,W,1]，逐张推理
    for i, s in enumerate(x):
        blob = (s - izp) / isz
        blob = np.clip(np.rint(blob), -128, 127).astype(np.int8)[None]
        it.set_tensor(ind['index'], blob)
        it.invoke()
        o = it.get_tensor(outd['index']).astype(np.float32)
        o = (o - ozp) / osz
        preds[i] = int(o.argmax())
    return preds


def report(tag, y, p):
    cm = np.zeros((2, 2), np.int32)
    for t, q in zip(y, p):
        cm[t, q] += 1
    print(f"\n  [{tag}]")
    print(f"    {'真实\\预测':<10}{'crop':>10}{'weed':>10}{'合计':>10}{'召回率':>10}")
    for i, name in enumerate(CLS):
        tot = cm[i].sum()
        rec = cm[i, i] / tot if tot else 0
        print(f"    {name:<10}{cm[i,0]:>10}{cm[i,1]:>10}{tot:>10}{rec:>9.1%}")
    print(f"    {'准确率':<10}{cm[0,0]/cm.sum():>10.1%}{cm[1,1]/cm.sum():>10.1%}"
          f"{np.trace(cm)/cm.sum():>10.1%}")
    # 两个方向的错误
    mis_crop = cm[0, 1] / max(cm[0].sum(), 1)   # 作物被当成杂草 -> 误打
    mis_weed = cm[1, 0] / max(cm[1].sum(), 1)   # 杂草被当成作物 -> 漏打
    print(f"    ⚠ 误打作物(crop→weed): {cm[0,1]}/{cm[0].sum()} = {mis_crop:.1%}")
    print(f"    ⚠ 漏打杂草 (weed→crop): {cm[1,0]}/{cm[1].sum()} = {mis_weed:.1%}")
    bal = (cm[0, 0] / max(cm[0].sum(), 1) + cm[1, 1] / max(cm[1].sum(), 1)) / 2
    print(f"    平衡准确率(balanced acc): {bal:.1%}")
    return cm, bal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.join(PROJ, r"models\weed_cls_int8.tflite"))
    ap.add_argument("--compare", default=None)
    a = ap.parse_args()

    x_va, y_va = load_split("val", input_size(a.model))
    print("=" * 64)
    print(f"  验证集 {len(y_va)} 张  (crop {int((y_va==0).sum())} / weed {int((y_va==1).sum())})")
    print("=" * 64)

    _, bal = report(os.path.basename(a.model), y_va, predict(a.model, x_va))
    if a.compare and os.path.exists(a.compare):
        _, bal2 = report(os.path.basename(a.compare) + " (对比)", y_va, predict(a.compare, x_va))
        print(f"\n  => 平衡准确率: 新 {bal:.1%} vs 旧 {bal2:.1%}"
              f"  ({'新模型更好' if bal > bal2 else '旧模型更好或持平'})")
    print("-" * 64)


if __name__ == "__main__":
    main()