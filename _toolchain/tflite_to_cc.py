# -*- coding: utf-8 -*-
r"""
tflite_to_cc.py —— int8 .tflite 的结构校验 + C 数组导出（单片机可直接 #include）

本机 note: TensorFlow / LiteRT 的原生库在这台机器上加载失败（DLL 问题，见
          _toolchain\check_env.py 输出），所以这里做**不依赖 TF 运行时**的校验：
            1. 容器级：TFL3 魔数、文件长度、flatbuffer 头解析
            2. 往返级：把导出的 .cc 再解析回字节，与源 .tflite 做 MD5 比对
          真正的算子/量化参数检查请在有 TF 环境的机器上跑（或上板实测）。

跑法:
  python _toolchain\tflite_to_cc.py                 # models 下全部 tflite
  python _toolchain\tflite_to_cc.py --in models\weed_cls_c8_int8.tflite
"""
import argparse
import glob
import hashlib
import os
import re
import struct
import sys

PROJ = r"E:\PlantDiseaseProject"
MODELS = os.path.join(PROJ, "models")

# C 数组符号名 —— 必须与原训练脚本保持一致，否则固件 #include 后链接失败。
# 来源：train_cls_int8.py -> g_weed_cls_model
#       train_cls_int8_c8.py -> g_weed_cls_c8_model
#不要凭文件名自动推导，weed_cls_c8_int8 的正确符号是 g_weed_cls_c8_model（没有 _int8）。
SYMBOLS = {
    "weed_cls_int8": "g_weed_cls_model",
    "weed_cls_c8_int8": "g_weed_cls_c8_model",
    "weed_cls_c8rgb_int8": "g_weed_cls_c8rgb_model",
}


def symbol_for(name):
    if name in SYMBOLS:
        return SYMBOLS[name]
    if name.startswith("weed_cls"):
        return "g_" + name.replace("weed_cls_", "weed_cls_") + "_model"
    return f"g_{name}_model"


def md5b(b):
    return hashlib.md5(b).hexdigest()


def parse_cc(path):
    """从 .cc 里把 C 数组字节抠回来"""
    txt = open(path, "r", encoding="utf-8", errors="replace").read()
    body = txt.split("{", 1)[1].rsplit("}", 1)[0]
    hexes = re.findall(r"0x([0-9a-fA-F]{2})", body)
    return bytes(int(h, 16) for h in hexes)


def sanity(raw, path):
    """不依赖 TF 的容器级校验"""
    ok = []
    n = len(raw)
    if raw[4:8] == b"TFL3":
        ok.append(f"魔数 TFL3 ✓")
    else:
        ok.append(f"⚠ 魔数异常 {raw[4:8]!r}")
    # FlatBuffer 根 table 的 soffset 存在文件头 0..4
    root_off = struct.unpack_from("<I", raw, 0)[0]
    ok.append(f"root table offset = {root_off} {'✓' if 0 < root_off < n else '⚠'}")
    # 统计可打印 ASCII 里的算子名（flatbuffer 里 operation 名字符串是明文）
    txt = raw.decode("latin1")
    ops = sorted({o for o in re.findall(r"\b(FULLY_CONNECTED|CONV_2D|DEPTHWISE_CONV_2D|"
                                        r"MAX_POOL_2D|AVERAGE_POOL_2D|SOFTMAX|RESHAPE|"
                                        r"QUANTIZE|DEQUANTIZE|ADD|MUL|MEAN|GLOBAL_AVERAGE|"
                                        r"LOGISTIC|PAD|CONCATENATION)\b", txt)})
    ok.append(f"内嵌算子名: {ops if ops else '(未识别)'}")
    return ok


def to_cc(raw, name, symbol, comment):
    hexs = ",\n".join("0x%02x" % b for b in raw)
    cc = (f'#include "{name}.h"\n'
          f"// {comment}, 大小 {len(raw)} B\n"
          f"const unsigned char {symbol}[] = {{\n{hexs}\n}};\n"
          f"const unsigned int {symbol}_len = {len(raw)};\n")
    hh = (f"#ifndef {name.upper().replace('.', '_')}_H\n"
          f"#define {name.upper().replace('.', '_')}_H\n"
          f"// {comment}\n#include <stdint.h>\n"
          f"extern const unsigned char {symbol}[];\n"
          f"extern const unsigned int {symbol}_len;\n"
          f"#endif\n")
    return cc, hh


def one(path, write=True):
    import numpy as np
    name = os.path.splitext(os.path.basename(path))[0]
    raw = open(path, "rb").read()
    print("-" * 70)
    print(f"  {os.path.basename(path)}   {len(raw)} B ({len(raw)/1024:.1f} KB)   md5 {md5b(raw)[:12]}")
    for s in sanity(raw, path):
        print(f"    {s}")

    # 已有 .cc 就做往返一致性校验
    cc_p = os.path.join(os.path.dirname(path), name + ".cc")
    h_p = os.path.join(os.path.dirname(path), name + ".h")
    if os.path.exists(cc_p):
        back = parse_cc(cc_p)
        same = md5b(back) == md5b(raw)
        print(f"    与现存 {name}.cc 往返比对: {'✓ 完全一致' if same else '✗ 不一致'}"
              f"  ({len(back)} B vs {len(raw)} B)")
    if os.path.exists(h_p):
        htxt = open(h_p, encoding="utf-8", errors="replace").read()
        sym = re.search(r"extern const unsigned char (\w+)\[\]", htxt)
        print(f"    头文件符号: {sym.group(1) if sym else '(未找到)'}")

    if not write:
        return
    symbol = symbol_for(name)
    cc, hh = to_cc(raw, name, symbol, f"{name} int8 模型")
    with open(cc_p, "w", encoding="utf-8") as f:
        f.write(cc)
    with open(h_p, "w", encoding="utf-8") as f:
        f.write(hh)
    back = parse_cc(cc_p)
    print(f"    已写出 {name}.cc ({os.path.getsize(cc_p)} B) + .h，符号 {symbol}"
          f"   往返校验 {'✓' if md5b(back)==md5b(raw) else '✗'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    # 有 TF/LiteRT 就顺带报一下张量信息，没有也不影响
    try:
        from ai_edge_litert.interpreter import Interpreter
        print("  [i] LiteRT 可用，可做运行时校验")
    except Exception:
        print("  [i] LiteRT/TF 不可用 -> 只做容器级 + 往返级校验（本机已知问题）")

    files = [args.inp] if args.inp else sorted(glob.glob(os.path.join(MODELS, "*.tflite")))
    if not files:
        sys.exit("[tflite] 没找到 .tflite")
    for p in files:
        one(p, write=not args.no_write)
    print("-" * 70)


if __name__ == "__main__":
    main()
