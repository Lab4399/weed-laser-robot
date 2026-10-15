# -*- coding: utf-8 -*-
"""C8T6 极限版: 48x48 灰度 crop/weed int8 分类。
设计目标: Flash<=40KB, 中间峰值<=12KB (STM32F103C8T6: 64K Flash / 20K SRAM)。
运行: py311\\python.exe train_cls_int8_c8.py
"""
import os, glob, sys
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

BASE = r'E:\PlantDiseaseProject\datasets\weed_cls'
SZ = 48
CLS = ['crop', 'weed']


def load_split(sp):
    xs, ys = [], []
    for c, name in enumerate(CLS):
        for f in glob.glob(os.path.join(BASE, sp, name, '*.jpg')):
            img = tf.image.decode_jpeg(tf.io.read_file(f), channels=1)
            img = tf.image.resize(img, [SZ, SZ])
            xs.append(tf.cast(img, tf.float32) - 128.0)
            ys.append(c)
    return tf.stack(xs), tf.constant(ys, tf.int32)


x_tr, y_tr = load_split('train')
x_va, y_va = load_split('val')
print('train', x_tr.shape, 'val', x_va.shape)

inp = keras.Input((SZ, SZ, 1))
# stride2 先把 48x48 降到 24x24，控制峰值特征图 24*24*16=9.2KB
h = layers.Conv2D(16, 3, strides=2, padding='same')(inp)
h = layers.BatchNormalization()(h)
h = layers.ReLU()(h)
h = layers.Conv2D(16, 3, padding='same')(h)
h = layers.BatchNormalization()(h)
h = layers.ReLU()(h)
h = layers.MaxPool2D(2)(h)          # 12x12x16
h = layers.Conv2D(32, 3, padding='same')(h)
h = layers.BatchNormalization()(h)
h = layers.ReLU()(h)
h = layers.GlobalAveragePooling2D()(h)
h = layers.Dense(2, activation='softmax')(h)
model = keras.Model(inp, h)
model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
model.summary()
model.fit(x_tr, y_tr, validation_data=(x_va, y_va), epochs=30, batch_size=32, verbose=1)

rep = tf.data.Dataset.from_tensor_slices((x_va, y_va)).batch(1)


def rep_gen():
    for xb, _ in rep:
        yield [xb.numpy()]


conv = tf.lite.TFLiteConverter.from_keras_model(model)
conv.optimizations = [tf.lite.Optimize.DEFAULT]
conv.representative_dataset = rep_gen
conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
conv.inference_input_type = tf.int8
conv.inference_output_type = tf.int8
tflite = conv.convert()

out_dir = r'E:\PlantDiseaseProject\models'
p = os.path.join(out_dir, 'weed_cls_c8_int8.tflite')
with open(p, 'wb') as f:
    f.write(tflite)
print('C8 tflite size =', len(tflite), 'bytes')

# 峰值中间张量评估（粗糙上界：单层最大 int8 张量）
interp = tf.lite.Interpreter(model_content=tflite)
interp.allocate_tensors()
sizes = []
for d in interp.get_tensor_details():
    if d['dtype'] in (np.int8, np.int32):
        sizes.append(int(np.prod(d['shape'])))
sizes.sort(reverse=True)
print('max tensor bytes =', sizes[:3])
print('C8T6 verdict: Flash', len(tflite), 'B; peak ~', sizes[0], 'B ->',
      'OK' if len(tflite) < 45000 and sizes[0] < 12000 else 'oversize')

hexs = ',\n'.join('0x%02x' % b for b in tflite)
cc = f'#include "weed_cls_c8_int8.h"\n// 48x48 gray int8 crop/weed, size {len(tflite)} B\nconst unsigned char g_weed_cls_c8_model[] = {{\n{hexs}\n}};\nconst unsigned int g_weed_cls_c8_model_len = {len(tflite)};\n'
h = ('#ifndef WEED_CLS_C8_INT8_H\n#define WEED_CLS_C8_INT8_H\n#include <stdint.h>\n'
     'extern const unsigned char g_weed_cls_c8_model[];\nextern const unsigned int g_weed_cls_c8_model_len;\n'
     '#define WEED_CLS_NC 2\n#define WEED_CLS_NAMES {"crop","weed"}\n#endif\n')
with open(os.path.join(out_dir, 'weed_cls_c8_int8.cc'), 'w') as f:
    f.write(cc)
with open(os.path.join(out_dir, 'weed_cls_c8_int8.h'), 'w') as f:
    f.write(h)
print('wrote weed_cls_c8_int8.cc/.h')
