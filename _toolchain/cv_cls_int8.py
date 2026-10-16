# -*- coding: utf-8 -*-
r"""
cv_cls_int8.py —— 分类模型的交叉验证评估（int8 量化后）

为什么必须有这个脚本
-------------------
之前所有分类模型指标都是在**验证集只有 35 张 crop** 的情况下测出来的：

    train:  crop 371  / weed 6380
    val:    crop 35   / weed 1038

35 张意味着每错判 1 张就是 2.86 个百分点，误打作物率 22.9% 的
**95% 置信区间是 [12.1%, 39.0%]，宽达 27 个百分点**。

后果很严重：
  * 「加权 48x48 平衡准确率 88.0% vs 96x96 的 85.7%」—— 差距只有 0.8 张样本，
    完全落在噪声里，**不能据此选型**
  * 「误打作物率从 34.3% 降到 22.9%」—— 置信区间大幅重叠，
    这个"提升"在统计上也不成立
  * 更糟的是，同一张原图裁出的多个贴图若被分到train 和 test 两侧，
    模型等于**见过**测试样本，指标会虚高

所以本脚本做两件事：
  1. **按原图分组** —— 贴图文件名形如 `latvia_00880_362_176.jpg`，
     前缀就是原图 ID。同一原图的所有贴图必须整体分到同一折，
     否则裁剪自同一张图的样本跨折 = 数据泄漏，指标虚高。
  2. **K 折交叉验证** —— 把全部 crop 样本（含原val 的 35 张）都用作评估，
     每张样本都被验证一次，得到 406 个样本上的指标而非 35 个。

结论以「均值 ± 标准差」报告，这才是能拿来做决策的数字。

跑法:
  python _toolchain\cv_cls_int8.py --size 48 --folds 5
  python _toolchain\cv_cls_int8.py --size 48 --epochs 20 --augment
"""

import argparse
import glob
import math
import os
import time

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

PROJ = r"E:\PlantDiseaseProject"
BASE = os.path.join(PROJ, r"datasets\weed_cls")
MODELS = os.path.join(PROJ, "models")
CLS = ['crop', 'weed']

SYMBOLS = {
    'weed_cls_int8': 'g_weed_cls_model',
    'weed_cls_c8_int8': 'g_weed_cls_c8_model',
}


def source_id(fn):
    """latvia_00880_362_176.jpg -> latvia_00880
    同一原图裁出的所有贴图必须分到同一折，否则数据泄漏。"""
    return os.path.splitext(fn)[0].rsplit('_', 2)[0]


def collect():
    """收集全部样本（train + val 合并），返回 (path, label, src)"""
    items = []
    for c, name in enumerate(CLS):
        for sp in ('train', 'val'):
            for f in sorted(glob.glob(os.path.join(BASE, sp, name, '*.jpg'))):
                items.append((f, c, source_id(os.path.basename(f))))
    return items


def load_paths(paths, sz):
    ds = tf.data.Dataset.from_tensor_slices(np.array(paths))
    ds = ds.map(lambda p: tf.image.resize(
        tf.image.decode_jpeg(tf.io.read_file(p), channels=1), [sz, sz]))
    return tf.stack(list(ds)).numpy().astype(np.float32) - 128.0


def build(sz):
    """结构与 train_cls_int8_balanced.py 完全一致，保证可比"""
    inp = keras.Input((sz, sz, 1))
    if sz == 48:
        h = layers.Conv2D(16, 3, strides=2, padding='same')(inp)
        h = layers.BatchNormalization()(h); h = layers.ReLU()(h)
        h = layers.Conv2D(16, 3, padding='same')(h)
        h = layers.BatchNormalization()(h); h = layers.ReLU()(h)
        h = layers.MaxPool2D(2)(h)
        h = layers.Conv2D(32, 3, padding='same')(h)
        h = layers.BatchNormalization()(h); h = layers.ReLU()(h)
        h = layers.GlobalAveragePooling2D()(h)
        out = layers.Dense(2, activation='softmax')(h)
    else:
        h = layers.Conv2D(16, 3, padding='same')(inp)
        h = layers.BatchNormalization()(h); h = layers.ReLU()(h)
        h = layers.MaxPool2D(2)(h)
        h = layers.Conv2D(32, 3, padding='same')(h)
        h = layers.BatchNormalization()(h); h = layers.ReLU()(h)
        h = layers.MaxPool2D(2)(h)
        h = layers.Conv2D(64, 3, padding='same')(h)
        h = layers.BatchNormalization()(h); h = layers.ReLU()(h)
        h = layers.GlobalAveragePooling2D()(h)
        h = layers.Dense(32, activation='relu')(h)
        out = layers.Dense(2, activation='softmax')(h)
    return keras.Model(inp, out)


def augment(x, rng):
    """数据增广：随机裁剪 + 翻转 + 亮度对比度扰动

    crop 样本只有 371 个，靠增广提升泛化比加模型容量有效得多。

    形状约定与 train_cls_int8_balanced.py 完全一致：
      输入 x 为 [N, sz, sz, 1] 的 float32，值域 [-128, 127]
      （load_paths 里做了 - 128.0 偏移，对齐int8 量化的 zero_point）
    """
    n = len(x)
    ch_out, cw_out = x.shape[1], x.shape[2]
    out = np.empty_like(x, dtype=np.float32)
    for i, s in enumerate(x):
        im = s[:, :, 0].astype(np.float32)      # [sz, sz]
        # 随机裁剪 85%~100%，保留主体
        sc = rng.uniform(0.85, 1.0)
        ch = max(int(ch_out * sc), 1)
        cw = max(int(cw_out * sc), 1)
        y0 = rng.integers(0, ch_out - ch + 1)
        x0 = rng.integers(0, cw_out - cw + 1)
        im = im[y0:y0 + ch, x0:x0 + cw]
        # 用 numpy 最近邻重采样缩放回原尺寸，避免 tf.image.resize 的形状歧义
        yi = np.rint(np.linspace(0, ch - 1, ch_out)).astype(int)
        xi = np.rint(np.linspace(0, cw - 1, cw_out)).astype(int)
        im = im[yi][:, xi]
        # 随机水平翻转
        if rng.random() < 0.5:
            im = im[:, ::-1]
        # 亮度/对比度扰动：模拟不同光照（零点是 128，故围绕 128 缩放）
        g = rng.uniform(0.8, 1.2)
        b = rng.uniform(-20.0, 20.0)
        im = np.clip((im - 128.0) * g + 128.0 + b, -128, 127)
        assert im.shape == (ch_out, cw_out), f'增广后形状异常: {im.shape}'
        out[i, :, :, 0] = im
    return out


def tflite_predict(tflite, x):
    """int8 推理：逐张调用（模型的输入张量固化为 batch=1，不能批量）"""
    it = tf.lite.Interpreter(model_content=tflite)
    it.allocate_tensors()
    ind, outd = it.get_input_details()[0], it.get_output_details()[0]
    isz, izp = ind['quantization'][0], ind['quantization'][1]
    osz, ozp = outd['quantization'][0], outd['quantization'][1]
    in_idx, out_idx = ind['index'], outd['index']
    pred = np.empty(len(x), np.int32)
    # 预先把整批量化好，避免每张重复算rint/clip
    q = np.clip(np.rint((x.astype(np.float32) - izp) / isz), -128, 127).astype(np.int8)
    for i in range(len(x)):
        it.set_tensor(in_idx, q[i:i + 1])
        it.invoke()
        o = it.get_tensor(out_idx).astype(np.float32)
        pred[i] = int(((o - ozp) / osz).argmax())
    return pred


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=48, choices=[48, 96])
    ap.add_argument('--out', default=None)
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--epochs', type=int, default=20)
    ap.add_argument('--augment', action='store_true', help='对少数类做增广')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--save', action='store_true', help='保存最后一折的模型')
    a = ap.parse_args()

    sz = a.size
    out_name = a.out or ('weed_cls_c8_int8' if sz == 48 else 'weed_cls_int8')

    print('=' * 70)
    print(f'  {out_name}  {sz}x{sz}  {a.folds} 折交叉验证（按原图分组防泄漏）')
    print('=' * 70)

    items = collect()
    srcs = sorted(set(it[2] for it in items))
    print(f'  全部样本{len(items)} 张  crop {sum(1 for i in items if i[1]==0)} / '
          f'weed {sum(1 for i in items if i[1]==1)}')
    print(f'  唯一原图 {len(srcs)} 张（同一原图的贴图必定同折）')

    rng = np.random.default_rng(a.seed)
    shuffled = list(srcs)
    rng.shuffle(shuffled)
    fold_of = {s: i % a.folds for i, s in enumerate(shuffled)}

    # 按折拆路径
    fold_paths = [[] for _ in range(a.folds)]
    for p, c, s in items:
        fold_paths[fold_of[s]].append(p)

    all_cm = np.zeros((2, 2), np.int64)
    per_fold = []
    last_tflite = None

    # 一次性解码全部图像，5 折共用，避免重复 IO + 解码
    t0 = time.time()
    X_all = load_paths([p for p, _, _ in items], sz)
    print(f'  已缓存 {len(items)} 张图像 @ {sz}x{sz}（耗时 {time.time()-t0:.1f}s）')
    print(f'  内存占用 {X_all.nbytes/1048576:.0f} MB')
    print()

    for k in range(a.folds):
        te_set = set(fold_paths[k])
        te_paths = fold_paths[k]

        # 用集合判定归属，避免 O(n^2) 的 in 列表扫描
        tr_idx = np.array([j for j, (p, c, s) in enumerate(items) if p not in te_set])
        te_idx = np.array([j for j, (p, c, s) in enumerate(items) if p in te_set])
        tr_y = np.array([items[j][1] for j in tr_idx], np.int32)
        te_y = np.array([items[j][1] for j in te_idx], np.int32)

        # 从一次性缓存里切片，不再每折重新解码全部图像
        x_tr = X_all[tr_idx]
        x_te = X_all[te_idx]

        n0 = max(int((tr_y == 0).sum()), 1)
        n1 = max(int((tr_y == 1).sum()), 1)
        cw = {0: len(tr_y) / (2 * n0), 1: len(tr_y) / (2 * n1)}

        tf.keras.utils.set_random_seed(a.seed + k)
        model = build(sz)
        model.compile(optimizer='adam', loss='sparse_categorical_crossentropy',
                      metrics=['accuracy'])

        if a.augment:
            # 手动增广：少数类做几何/光度扰动
            idx0 = np.where(tr_y == 0)[0]
            idx1 = np.where(tr_y == 1)[0]
            # 上限 2 倍而非 3 倍：crop 从 325到 975 已足够，
            # 再多只会让每折训练时间翻倍而收益递减
            n_aug = min(len(idx1) - len(idx0), len(idx0) * 2)
            if n_aug > 0:
                t0 = time.time()
                pick = rng.choice(idx0, size=n_aug, replace=True)
                x_aug = augment(x_tr[pick], rng)
                x_tr = np.concatenate([x_tr, x_aug])
                tr_y = np.concatenate([tr_y, np.zeros(n_aug, np.int32)])
                cw = {0: len(tr_y) / (2 * (n0 + n_aug)), 1: len(tr_y) / (2 * n1)}
                print(f'      增广: +{n_aug} 张 crop（原{len(idx0)} -> {len(idx0)+n_aug}）'
                      f' 耗时 {time.time()-t0:.1f}s')

        t0 = time.time()
        model.fit(x_tr, tr_y, epochs=a.epochs, batch_size=32, verbose=0,
                  class_weight=cw)
        t_train = time.time() - t0

        # ---- int8 量化后在测试折上评估 ----
        rep = tf.data.Dataset.from_tensor_slices(x_te[:64]).batch(1)

        def rep_gen():
            for xb in rep:
                yield [xb]

        t0 = time.time()
        conv = tf.lite.TFLiteConverter.from_keras_model(model)
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = rep_gen
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.int8
        conv.inference_output_type = tf.int8
        tflite = conv.convert()
        t_quant = time.time() - t0
        last_tflite = tflite

        t0 = time.time()
        pred = tflite_predict(tflite, x_te)
        t_pred = time.time() - t0
        # 用 bincount 累加混淆矩阵：比 np.add.at 快一个数量级
        # （np.add.at 逐元素串行累加，7824 个样本要几十毫秒）
        flat = te_y * 2 + pred
        all_cm += np.bincount(flat, minlength=4).reshape(2, 2)
        cm = np.bincount(flat, minlength=4).reshape(2, 2)
        bal = (cm[0, 0] / max(cm[0].sum(), 1) + cm[1, 1] / max(cm[1].sum(), 1)) / 2
        per_fold.append(bal)
        print(f'  折 {k+1}/{a.folds}: 测试 {len(te_y)} (crop {int((te_y==0).sum())})'
              f'  平衡准确率 {bal:.1%}  tflite {len(tflite)} B'
              f'  [训练 {t_train:.0f}s 量化 {t_quant:.0f}s 推理 {t_pred:.0f}s]',
              flush=True)

    # ---- 汇总 ----
    n_crop = int(all_cm[0].sum())
    n_weed = int(all_cm[1].sum())
    rec_c = all_cm[0, 0] / max(n_crop, 1)
    rec_w = all_cm[1, 1] / max(n_weed, 1)
    bal = (rec_c + rec_w) / 2
    mis_c, mis_w = all_cm[0, 1] / max(n_crop, 1), all_cm[1, 0] / max(n_weed, 1)
    lo_c, hi_c = wilson(int(all_cm[0, 1]), n_crop)
    lo_w, hi_w = wilson(int(all_cm[1, 0]), n_weed)

    print('\n' + '=' * 70)
    print(f'  {a.folds} 折汇总（int8 量化后，全部 {n_crop + n_weed} 个样本各验证一次）')
    print('=' * 70)
    print(f"    {'真实\\预测':<10}{'crop':>10}{'weed':>10}{'合计':>10}{'召回':>10}")
    for i, nm in enumerate(CLS):
        tot = all_cm[i].sum()
        r = all_cm[i, i] / max(tot, 1)
        print(f"    {nm:<10}{all_cm[i,0]:>10}{all_cm[i,1]:>10}{tot:>10}{r:>9.1%}")
    print()
    print(f'    平衡准确率 {bal:.1%}   (折间 std {np.std(per_fold):.1%}，'
          f'区间 {min(per_fold):.1%}~{max(per_fold):.1%})')
    print(f'    weed 召回 {rec_w:.1%}')
    print(f'    crop 召回 {rec_c:.1%}')
    print(f'    误打作物 {mis_c:.1%}  (错判 {all_cm[0,1]}/{n_crop}，'
          f'95% CI [{lo_c:.1%}, {hi_c:.1%}])')
    print(f'    漏打杂草 {mis_w:.1%}  (错判 {all_cm[1,0]}/{n_weed}，'
          f'95% CI [{lo_w:.1%}, {hi_w:.1%}])')
    print()
    print(f'    ✅ crop 评估样本从 35 提升到 {n_crop} —— '
          f'置信区间宽度从 27 个百分点降到 {(hi_c-lo_c)*100:.1f} 个百分点')

    if a.save and last_tflite is not None:
        sym = SYMBOLS[out_name]
        path = os.path.join(MODELS, out_name + '.tflite')
        with open(path, 'wb') as f:
            f.write(last_tflite)
        hexs = ',\n'.join('0x%02x' % b for b in last_tflite)
        with open(os.path.join(MODELS, out_name + '.cc'), 'w') as f:
            f.write(f'#include "{out_name}.h"\n'
                    f'// {sz}x{sz} gray int8 crop/weed, size {len(last_tflite)} B\n'
                    f'const unsigned char {sym}[] = {{\n{hexs}\n}};\n'
                    f'const unsigned int {sym}_len = {len(last_tflite)};\n')
        with open(os.path.join(MODELS, out_name + '.h'), 'w') as f:
            f.write(f'#ifndef {out_name.upper()}_H\n#define {out_name.upper()}_H\n'
                    '#include <stdint.h>\n'
                    f'extern const unsigned char {sym}[];\n'
                    f'extern const unsigned int {sym}_len;\n'
                    '#define WEED_CLS_NC 2\n#define WEED_CLS_NAMES {"crop","weed"}\n#endif\n')
        print(f'\n  已写出 {out_name}.tflite/.cc/.h，符号 {sym}')
        print(f'  ⚠ 注意：这是第 {a.folds} 折的模型，只用了 {(a.folds-1)/a.folds:.0%} 数据')
        print(f'    正式部署建议用 --save 时提高 folds 或改用全量训练')

    print('-' * 70)


if __name__ == '__main__':
    main()