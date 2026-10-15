# 🌿 除草小车视觉识别与激光除草系统

基于 YOLOv8n 的**作物 / 杂草二类目标检测** + 激光除草执行链，面向实验室田间作业验证。

>本仓库对应交付包中的 **`01_视觉识别`** 部分，按原路径 `E:\PlantDiseaseProject` 组织，
> 原有脚本可直接运行。

---

## 📐 系统架构

```
┌─────────────┐   USART3    ┌──────────────────┐  串口   ┌──────────────┐
│ OpenMV      │ ──────────► │ STM32F407        │ ──────► │ 激光瞄准控制板│
│ (STM32H7+   │   识别结果   │ GoodDog 行走底盘  │         │ (Arduino)    │
│  OV7725)    │              │ 差速闭环 + 安全   │         │ 云台 + 激光  │
└─────────────┘              └──────────────────┘         └──────────────┘
       ▲
       │识别模型
┌─────────────┐
│ YOLOv8n  .pt│  PC 端训练 / 验证
│ int8 .tflite│  单片机端推理
└─────────────┘
```

| 层级 | 硬件 / 模型 | 说明 |
|---|---|---|
| 识别端 | OpenMV（STM32H7 + OV7725） | `openmv/` |
| 主控 | STM32F407 GoodDog 行走底盘 | 固件在交付包 `02_单片机固件` |
| 执行 | 激光除草模块（Arduino 云台 + 激光） | `laser_strike/` |
| 算法 | YOLOv8n 检测 + int8 量化分类 | `models/` |

---

## 📊 模型指标（关键结论）

本仓库的 `models/best.pt` 是在**真实田间数据集**上重训的新模型，
显著优于交付包自带的原始基线：

| 项 |原始基线 | **新模型** | 变化 |
|---|---|---|---|
| 训练图数 | 171 | **1000** | 5.8× |
| 验证图数 | 30 | **176** | 5.9× |
| Precision | — | **0.736** | — |
| Recall | — | **0.781** | — |
| **mAP50** | 0.68 | **0.814** | **+19.7%** |
| mAP50-95 | — | **0.558** | — |

**逐类指标**（验证集 176 图 / 1075 框）

| 类别 | 实例数 | P | R | mAP50 |
|---|---|---|---|---|
| `crop`（作物，不打） | 35 | 0.731 | 0.743 | 0.800 |
| **`weed`（杂草，打击）** | **1040** | **0.742** | **0.818** | **0.828** |

> ⚠️ 原始基线只用171 张图就刷到 mAP50 0.68，属于**小数据集过拟合**，
> 泛化能力存疑。新模型基于 1176 张真实田间图，可信度更高。
>
> ⚠️ 注意区分：根目录 `best.pt`（交付包自带旧基线）已被 `.gitignore` 排除，
> 避免与 `models/best.pt`（新模型）同名混淆。旧基线完整归档在
> `models/weed_det_orig_171img_20261007/`。

**训练环境**：GTX 1660 SUPER / YOLOv8n / 640×640 / batch 8 / 100 epochs / 37 分钟
完整实录见 [`本机训练部署实录_20261011.md`](本机训练部署实录_20261011.md)

---

## 🚀 快速开始

### 1. 环境准备

```bash
# 需要 Python 3.9+；GPU 训练需 PyTorch（按自己显卡驱动选 CUDA 版本）
pip install ultralytics opencv-python numpy pyarrow pandas
```

### 2. 准备数据集

数据集不入库，用脚本从 HuggingFace 转换生成：

```bash
python _toolchain/parquet2yolo.py --src <crop_weed_latvia.parquet> --clean
```

数据源：`Project-AgML/crop_weed_detection_latvia`（1176 张 / 7853框 / 2 类）

> ⚠️ **类别顺序坑**：HF 里 `0=weed, 1=crop`，与本项目约定**相反**。
> 转换脚本已做重映射 → `0=crop` `1=weed`，与 `laser_strike/config.py`
> 的 `TARGET_CLASSES=[1]` 对齐。改数据集时务必留意。

### 3. 训练

```bash
python train_weed.py --data datasets/weed_yolo/data.yaml --epochs 100 --batch 8
```

产出自动复制到 `models/best.pt`（`laser_strike/config.py` 的加载路径）。

### 4. 看效果

双击 `一键启动GUI.bat`，或用命令行：

```bash
python gui/plant_disease_gui.py       # 图片 / 摄像头检测
```

### 5. 部署导出

```bash
# PT → ONNX → OpenCV DNN 实测（项目部署路径，不依赖 onnxruntime）
python _toolchain/deploy_export.py --weights models/best.pt --no-simplify

# int8 tflite 校验 + 生成 C 数组（单片机可直接 #include）
python _toolchain/tflite_to_cc.py
```

---

## 📁 目录结构

```
.
├── laser_strike/            激光除草执行控制
│   ├── config.py            类别定义、串口、模型路径（先看这个）
│   ├── detector.py          杂草检测
│   ├── aiming.py            云台瞄准
│   ├── actuator.py          激光触发
│   ├── gooddog.py           底盘通信
│   ├── mission.py           作业流程编排
│   ├── main.py              入口（--sim 仿真 / --port COMx 真机）
│   ├── arduino/             激光云台固件
│   └── _docs/               硬件设计方案 + 系统框图
├── openmv/                  OpenMV 识别端脚本
│   ├── main.py
│   └── weeder.py
├── gui/                     PC 端演示界面
├── models/                  模型
│   ├── best.pt              ★ 新模型（mAP50 0.814）
│   ├── best_orig_171img_20261007.pt   原始基线备份
│   ├── weed_det/            新模型训练输出（含 results.csv）
│   ├── weed_det_orig_171img_20261007/  基线训练输出
│   └── weed_cls_*.tflite/.cc/.h        int8 量化分类模型
├── _toolchain/              训练部署工具链（本机新增）
│   ├── check_env.py         环境自检
│   ├── parquet2yolo.py      HF parquet → YOLO
│   ├── deploy_export.py     PT → ONNX → OpenCV DNN
│   ├── tflite_to_cc.py      int8 校验 + C 数组导出
│   └── run_train.bat        训练启动器
├── train_weed.py            YOLOv8n 二类检测训练
├── tools_crop_cls.py        按检测框裁剪分类图
├── train_cls_int8*.py       int8 量化分类模型训练
├── onnx_inference.py         ONNX 推理（纯 OpenCV）
└── *.md                     各类文档
```

---

## 🔧 模型格式说明（避坑）

| 格式 | 用途 | 能否在单片机跑 |
|---|---|---|
| `.pt` | PyTorch 权重 | ❌ **只能 PC 跑** |
| `.onnx` | 跨平台推理（OpenCV DNN） | ⚠️ 部分嵌入式框架可跑 |
| `.tflite` | TensorFlow Lite，int8 量化 | ✅ |
| `.cc` / `.h` | tflite 转成的 C 数组 | ✅ **直接编译进固件** |

单片机端请用 `.tflite` 或已转好的 `.cc` / `.h`。

---

## 📚 文档

| 文档 | 内容 |
|---|---|
| [本机训练部署实录](本机训练部署实录_20261011.md) | 从零搭环境、拿数据、训练、部署的完整实录 |
| [训练指南](训练指南.md) | 训练参数与调优 |
| [模型优化指南](模型优化指南.md) | mAP 提升技巧 |
| [数据集下载指南](数据集下载指南.md) | 数据来源说明 |
| [OpenMV 集成指南](OpenMV集成指南.md) | 识别端集成 |
| [完整项目指南](完整项目指南.md) | 整体流程 |
| [修复说明](修复说明.md) | 已知问题与修复 |
| [laser_strike/系统方案.md](laser_strike/系统方案.md) | 激光除草执行方案 |
| [laser_strike/_docs/激光瞄准板硬件设计方案.md](laser_strike/_docs/激光瞄准板硬件设计方案.md) | 控制板硬件 |

---

## ⚠️ 已知问题

1. **本机环境**：`onnxruntime` / `tensorflow` / `litert` 在部分 Windows 虚拟化环境下加载原生库会段错误。项目部署走 **OpenCV DNN**，不依赖它们；ONNX 导出加 `--no-simplify` 可跳过 `onnxslim`。
2. **AMP**：GTX 1660 SUPER 上 ultralytics AMP 自检未通过会自动降级 fp32，属正常现象。
3. **int8 分类模型**：`models/weed_cls_*.tflite` 仍是交付包原有产物，**尚未**用新数据集重训。

---

## 📄 许可证

仅供学习与研究使用。

## 🙏 致谢

- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)
- 数据集：[Project-AgML/crop_weed_detection_latvia](https://huggingface.co/datasets/Project-AgML/crop_weed_detection_latvia)