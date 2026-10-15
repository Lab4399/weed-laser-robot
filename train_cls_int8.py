# -*- coding: utf-8 -*-
"""
C8T6 适配: crop/weed 96x96 灰度 int8 分类训练 -> 全整型 .tflite
输入约定: 0..255 灰度 减128 -> int8(-128..127)  (与 stm32_pest_skeleton 一致)
运行: py311\\python.exe train_cls_int8.py
产物: E:\\PlantDiseaseProject\\models\\weed_cls_int8.tflite (+ .cc 供 C8T6 TFLM)
"""
import os, glob
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

BASE = r'E:\PlantDiseaseProject\datasets\weed_cls'
SZ = 96
CLS = ['crop', 'weed']


def load_split(sp):
    xs, ys = [], []
    for c, name in enumerate(CLS):
        for f in glob.glob(os.path.join(BASE, sp, name, '*.jpg')):
            img = tf.image.decode_jpeg(tf.io.read_file(f), channels=1)
            img = tf.image.resize(img, [SZ, SZ])
            xs.append(tf.cast(img, tf.float32) - 128.0)  # 与 int8 减128 对齐
            ys.append(c)
    x = tf.stack(xs)
    return x, tf.constant(ys, tf.int32)


print('loading data...')
x_tr, y_tr = load_split('train')
x_va, y_va = load_split('val')
print('train', x_tr.shape, 'val', x_va.shape)

inp = keras.Input((SZ, SZ, 1))
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
model = keras.Model(inp, out)
model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
model.summary()

model.fit(x_tr, y_tr, validation_data=(x_va, y_va), epochs=30, batch_size=32, verbose=1)

# ---- 全整型 int8 量化 ----
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

out_dir = r'E:\PlantDiseaseProject\models'
os.makedirs(out_dir, exist_ok=True)
p = os.path.join(out_dir, 'weed_cls_int8.tflite')
with open(p, 'wb') as f:
    f.write(tflite)
print('tflite size =', len(tflite), 'bytes ->', p)

# ---- 模型体积评估（C8T6: Flash 64KB / SRAM 20KB）----
interp = tf.lite.Interpreter(model_content=tflite)
interp.allocate_tensors()
in_d = interp.get_input_details()[0]
out_d = interp.get_output_details()[0]
print('input', in_d['shape'], in_d['dtype'], 'quant', in_d.get('quantization'))
print('output', out_d['shape'], out_d['dtype'])
# 粗估 arena: 权重(≈tflite-头) + 中间 int8 张量峰值
peaks = []
for d in interp.get_tensor_details():
    if d['dtype'] == np.int8 or d['dtype'] == np.int32:
        peaks.append(int(np.prod(d['shape'])))
peaks.sort(reverse=True)
arena_est = sum(peaks[:6]) + 2048
print('C8T6 评估: Flash 需 =', len(tflite), 'B ; 建议 arena ≈', arena_est, 'B (SRAM 20KB 内)')
print('可行' if len(tflite) < 50000 and arena_est < 12000 else '需缩小模型')

# ---- 导出 .cc 数组（供 TFLM/CMSIS 工程引用）----
hexs = ',\n'.join('0x%02x' % b for b in tflite)
cc = f'#include "weed_cls_int8.h"\n// 96x96 灰度 int8 crop/weed 分类模型, 大小 {len(tflite)} B\nconst unsigned char g_weed_cls_model[] = {{\n{hexs}\n}};\nconst unsigned int g_weed_cls_model_len = {len(tflite)};\n'
h = f'#ifndef WEED_CLS_INT8_H\n#define WEED_CLS_INT8_H\n// crop/weed 分类 int8 (96x96 灰) 模型, C8T6 可用\n#include <stdint.h>\nextern const unsigned char g_weed_cls_model[];\nextern const unsigned int g_weed_cls_model_len;\n#define WEED_CLS_NC 2\n#define WEED_CLS_NAMES {{"crop","weed"}}\n#endif\n'
with open(os.path.join(out_dir, 'weed_cls_int8.cc'), 'w') as f:
    f.write(cc)
with open(os.path.join(out_dir, 'weed_cls_int8.h'), 'w') as f:
    f.write(h)
print('wrote weed_cls_int8.cc/.h in', out_dir)
