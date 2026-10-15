# -*- coding: utf-8 -*-
r"""
train_cls_int8_balanced.py —— 带类别加权的 int8 分类训练

为什么需要这个脚本
------------------
原train_cls_int8.py / train_cls_int8_c8.py 直接在新数据集上训练，但新数据
（Project-AgML/crop_weed_detection_latvia）裁出的贴图是**严重失衡**的：

    train:  crop 371  / weed 6380     = 17 : 1
    val:    crop 35   / weed 1038     = 30 : 1

原脚本不加权，实测结果：新模型 weed 召回 99.8% 但**误打作物率 34.3%**
（1/3 的作物会被激光打），平衡准确率 82.8%，与旧模型 83.1% 持平 ——
换句话说拿回来的不是提升，而是把错误从"漏打杂草"搬到了"打坏作物"。

本脚本的改动（模型结构、量化方式、输出路径、C 符号名全部保持不变）
    1. class_weight = 样本数的反比，给少数类 crop 补上损失权重
    2. 少数类做水平翻转增广，把 crop 的有效样本翻倍
    3. 训练后直接输出逐类召回 / 误打率 / 漏打率

模型结构与 C8T6 内存约束完全沿用原脚本，改动只在训练侧。

跑法:
  python _toolchain\train_cls_int8_balanced.py --size 48 --out weed_cls_c8_int8
  python _toolchain\train_cls_int8_balanced.py --size 96 --out weed_cls_int8
"""
import argparse
import glob
import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

PROJ = r"E:\PlantDiseaseProject"
BASE = os.path.join(PROJ, r"datasets\weed_cls")
MODELS = os.path.join(PROJ, "models")
CLS = ['crop', 'weed']

# C 数组符号名 —— 必须与原训练脚本一致，固件按这些名字链接
SYMBOLS = {
    'weed_cls_int8': 'g_weed_cls_model',
    'weed_cls_c8_int8': 'g_weed_cls_c8_model',
}


def load_split(sp, sz, flip_minority=False):
    per = {0: [], 1: []}
    for c, name in enumerate(CLS):
        for f in sorted(glob.glob(os.path.join(BASE, sp, name, '*.jpg'))):
            img = tf.image.decode_jpeg(tf.io.read_file(f), channels=1)
            img = tf.image.resize(img, [sz, sz])
            per[c].append(tf.cast(img, tf.float32) - 128.0)
    xs, ys = [], []
    for c in (0, 1):
        arr = tf.stack(per[c])
        xs.append(arr)
        ys.append(tf.fill([len(per[c])], c))
        if flip_minority and sp == 'train':
            # 少数类水平翻转增广：田间作物左右翻转后语义不变
            fl = tf.image.flip_left_right(arr)
            xs.append(fl)
            ys.append(tf.fill([len(per[c])], c))
    x = tf.concat(xs, 0)
    y = tf.concat(ys, 0)
    # 训练集打乱（增广后顺序是拼接的）
    if sp == 'train':
        idx = tf.random.shuffle(tf.range(len(y)))
        x = tf.gather(x, idx)
        y = tf.gather(y, idx)
    return x, y, {0: len(per[0]), 1: len(per[1])}


def build(sz):
    inp = keras.Input((sz, sz, 1))
    if sz == 48:
        # C8T6 极限版（沿用 train_cls_int8_c8.py 结构）
        h = layers.Conv2D(16, 3, strides=2, padding='same')(inp)
        h = layers.BatchNormalization()(h)
        h = layers.ReLU()(h)
        h = layers.Conv2D(16, 3, padding='same')(h)
        h = layers.BatchNormalization()(h)
        h = layers.ReLU()(h)
        h = layers.MaxPool2D(2)(h)
        h = layers.Conv2D(32, 3, padding='same')(h)
        h = layers.BatchNormalization()(h)
        h = layers.ReLU()(h)
        h = layers.GlobalAveragePooling2D()(h)
        out = layers.Dense(2, activation='softmax')(h)
    else:
        # 96x96 版（沿用 train_cls_int8.py 结构）
        h = layers.Conv2D(16, 3, padding='same')(inp)
        h = layers.BatchNormalization()(h)
        h = layers.ReLU()(h)
        h = layers.MaxPool2D(2)(h)
        h = layers.Conv2D(32, 3, padding='same')(h)
        h = layers.BatchNormalization()(h)
        h = layers.ReLU()(h)
        h = layers.MaxPool2D(2)(h)
        h = layers.Conv2D(64, 3, padding='same')(h)
        h = layers.BatchNormalization()(h)
        h = layers.ReLU()(h)
        h = layers.GlobalAveragePooling2D()(h)
        h = layers.Dense(32, activation='relu')(h)
        out = layers.Dense(2, activation='softmax')(h)
    return keras.Model(inp, out)


def per_class_report(y_true, y_pred):
    cm = np.zeros((2, 2), np.int32)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    print('    ' + '-' * 52)
    print(f"    {'真实\\预测':<8}{'crop':>10}{'weed':>10}{'合计':>10}{'召回':>10}")
    for i, n in enumerate(CLS):
        tot = cm[i].sum()
        rec = cm[i, i] / tot if tot else 0
        print(f"    {n:<8}{cm[i,0]:>10}{cm[i,1]:>10}{tot:>10}{rec:>9.1%}")
    acc = np.trace(cm) / cm.sum()
    bal = (cm[0, 0] / max(cm[0].sum(), 1) + cm[1, 1] / max(cm[1].sum(), 1)) / 2
    mis_crop = cm[0, 1] / max(cm[0].sum(), 1)
    mis_weed = cm[1, 0] / max(cm[1].sum(), 1)
    print(f"    总体准确率 {acc:.1%}   平衡准确率 {bal:.1%}")
    print(f"    ⚠ 误打作物 (crop→weed): {cm[0,1]}/{cm[0].sum()} = {mis_crop:.1%}")
    print(f"    ⚠ 漏打杂草 (weed→crop): {cm[1,0]}/{cm[1].sum()} = {mis_weed:.1%}")
    return bal, mis_crop, mis_weed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=48, choices=[48, 96])
    ap.add_argument('--out', default=None, help='模型名前缀，默认按 size 推断')
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--no-flip', action='store_true')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    sz = a.size
    out_name = a.out or ('weed_cls_c8_int8' if sz == 48 else 'weed_cls_int8')
    tf.random.set_seed(a.seed)

    print('=' * 64)
    print(f'  {out_name}  {sz}x{sz} 灰度 int8  ·  加权训练')
    print('=' * 64)
    x_tr, y_tr, cnt = load_split('train', sz, flip_minority=not a.no_flip)
    x_va, y_va, _ = load_split('val', sz)
    print(f'  原始 train: crop {cnt[0]} / weed {cnt[1]}'
          f'  ({"已做水平翻转增广" if not a.no_flip else "未增广"})')
    print(f'  训练集实际 {len(y_tr)} 张  验证集 {len(y_va)} 张')

    y_np = y_tr.numpy()
    n0 = int((y_np == 0).sum())
    n1 = int((y_np == 1).sum())
    cw = {0: float(len(y_np)) / (2 * n0), 1: float(len(y_np)) / (2 * n1)}
    print(f'  class_weight: crop {cw[0]:.2f}  weed {cw[1]:.2f}')

    model = build(sz)
    model.compile(optimizer='adam', loss='sparse_categorical_crossentropy',
                  metrics=['accuracy'])
    model.fit(x_tr, y_tr, validation_data=(x_va, y_va), epochs=a.epochs,
              batch_size=32, verbose=2, class_weight=cw)

    print('\n  [float 模型逐类表现]')
    p = model.predict(x_va, batch_size=256, verbose=0).argmax(1)
    per_class_report(y_va.numpy(), p)

    # ---- 全整型 int8 量化（与原脚本一致）----
    rep = tf.data.Dataset.from_tensor_slices((x_va, y_va)).batch(1)

    def rep_gen():
        for xb, _ in rep:
            yield [xb]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep_gen
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    tflite = conv.convert()

    path = os.path.join(MODELS, out_name + '.tflite')
    with open(path, 'wb') as f:
        f.write(tflite)
    print(f'\n  tflite {len(tflite)} B -> {path}')

    # ---- int8 量化后逐类表现（这才是最终要看的）----
    it = tf.lite.Interpreter(model_content=tflite)
    it.allocate_tensors()
    ind, outd = it.get_input_details()[0], it.get_output_details()[0]
    isz, izp = ind['quantization'][0], ind['quantization'][1]
    osz, ozp = outd['quantization'][0], outd['quantization'][1]
    pred = np.empty(len(x_va), np.int32)
    for i, s in enumerate(x_va.numpy()):
        b = np.clip(np.rint((s - izp) / isz), -128, 127).astype(np.int8)[None]
        it.set_tensor(ind['index'], b)
        it.invoke()
        o = it.get_tensor(outd['index']).astype(np.float32)
        pred[i] = int(((o - ozp) / osz).argmax())
    print('  [int8 量化后逐类表现]')
    per_class_report(y_va.numpy(), pred)

    sizes = sorted((int(np.prod(d['shape'])) for d in it.get_tensor_details()
                    if d['dtype'] in (np.int8, np.int32)), reverse=True)
    print(f'\n  C8T6 评估: Flash {len(tflite)} B; 峰值张量 {sizes[0]} B -> '
          + ('OK' if len(tflite) < 45000 and sizes[0] < 12000 else '超限'))

    # ---- C 数组（符号名与原脚本一致）----
    sym = SYMBOLS[out_name]
    hexs = ',\n'.join('0x%02x' % b for b in tflite)
    cc = (f'#include "{out_name}.h"\n'
          f'// {sz}x{sz} gray int8 crop/weed, size {len(tflite)} B\n'
          f'const unsigned char {sym}[] = {{\n{hexs}\n}};\n'
          f'const unsigned int {sym}_len = {len(tflite)};\n')
    hh = (f'#ifndef {out_name.upper()}_H\n#define {out_name.upper()}_H\n'
          '#include <stdint.h>\n'
          f'extern const unsigned char {sym}[];\n'
          f'extern const unsigned int {sym}_len;\n'
          '#define WEED_CLS_NC 2\n#define WEED_CLS_NAMES {"crop","weed"}\n#endif\n')
    with open(os.path.join(MODELS, out_name + '.cc'), 'w') as f:
        f.write(cc)
    with open(os.path.join(MODELS, out_name + '.h'), 'w') as f:
        f.write(hh)
    print(f'  已写出 {out_name}.cc/.h，符号 {sym}')
    print('-' * 64)


if __name__ == '__main__':
    main()