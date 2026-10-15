# -*- coding: utf-8 -*-
"""C8T6 RGB 48x48 crop/weed int8: 训练+量化+保守阈值评估 一体化"""
import os, glob
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

BASE = r'E:\PlantDiseaseProject\datasets\weed_cls'
OUT = r'E:\PlantDiseaseProject\models\weed_cls_c8rgb_int8.tflite'
SZ = 48
CH = 3
CLS = ['crop', 'weed']


def load_split(sp):
    xs, ys = [], []
    for c, name in enumerate(CLS):
        for f in glob.glob(os.path.join(BASE, sp, name, '*.jpg')):
            img = tf.image.decode_jpeg(tf.io.read_file(f), channels=CH)
            img = tf.image.resize(img, [SZ, SZ])
            xs.append(tf.cast(img, tf.float32) - 128.0)
            ys.append(c)
    return tf.stack(xs), tf.constant(ys, tf.int32)


x_tr, y_tr = load_split('train')
x_va, y_va = load_split('val')
print('train', x_tr.shape, 'val', x_va.shape)

inp = keras.Input((SZ, SZ, CH))
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
h = layers.Dense(2, activation='softmax')(h)
model = keras.Model(inp, h)
model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])
model.fit(x_tr, y_tr, validation_data=(x_va, y_va), epochs=40, batch_size=32, verbose=0)
_, acc = model.evaluate(x_va, y_va, verbose=0)
print('float val acc =', round(float(acc), 4))

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
with open(OUT, 'wb') as f:
    f.write(tflite)
print('tflite bytes =', len(tflite))

interp = tf.lite.Interpreter(model_content=tflite)
interp.allocate_tensors()
in_d = interp.get_input_details()[0]
out_d = interp.get_output_details()[0]
oscal, ozero = out_d.get('quantization') or (1.0, 0)
print('in', in_d['shape'], in_d['dtype'])


def preprocess(f):
    img = tf.image.decode_jpeg(tf.io.read_file(f), channels=CH)
    img = tf.image.resize(img, [SZ, SZ])
    return np.clip(tf.cast(img, tf.int32).numpy() - 128, -128, 127).astype(np.int8)


def weed_score(f):
    interp.set_tensor(in_d['index'], preprocess(f)[None])
    interp.invoke()
    q = interp.get_tensor(out_d['index'])[0].astype(np.float32)
    lo = oscal * (q - ozero)
    e = np.exp(lo - lo.max())
    return float((e / e.sum())[1])


crop = [weed_score(f) for f in glob.glob(os.path.join(BASE, 'val', 'crop', '*.jpg'))]
weed = [weed_score(f) for f in glob.glob(os.path.join(BASE, 'val', 'weed', '*.jpg'))]
print(f'crop n={len(crop)} weed n={len(weed)}')
for t in (0.5, 0.6, 0.7, 0.8, 0.9):
    cm = sum(1 for s in crop if s >= t) / len(crop)
    wr = sum(1 for s in weed if s >= t) / len(weed)
    print(f'thr={t:.2f}: crop_err={cm:.1%} weed_recall={wr:.1%}')
print('DONE')
