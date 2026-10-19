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

## 📊 int8 分类模型（单片机端）

检测框裁剪出贴图后做 crop/weed 二分类，用于确认打击目标。

### 为什么需要重训 + 加权

用本仓库数据集裁出的贴图**严重失衡**（作物在田间图里本来就少）：

| 划分 | crop | weed | 比例 |
|---|---|---|---|
| train | 371 | 6380 | **17 : 1** |
| val | 35 | 1038 | **30 : 1** |

直接用原`train_cls_int8.py` 训练会得到"看起来很好、实际危险"的模型：
weed 召回 99.8%，但**误打作物率 34.3%**（1/3 作物会被激光打），
平衡准确率 82.8% 与旧模型 83.1% 持平 —— 等于把错误从"漏打杂草"搬到了"打坏作物"。

`_toolchain/train_cls_int8_balanced.py` 保持模型结构 / 量化方式 / C 符号名不变，
只改训练侧：`class_weight` 取样本数反比 + 少数类水平翻转增广。

### ⚠️ 下面这张表不可信，请勿用于选型

| 模型 | 输入 | weed 召回 | crop 召回 | **误打作物** | **漏打杂草** | **平衡准确率** | Flash | C8T6 |
|---|---|---|---|---|---|---|---|---|
| 交付包旧模型 | — | 80.5% | 85.7% | 14.3% | 19.5% | 83.1% | — | — |
| 原脚本直训 | 96×96 | 99.8% | 65.7% | 34.3% | 0.2% | 82.8% | 34.7 KB | ❌ 超限 |
| 加权 48×48 | 48×48 | 98.9% | 77.1% | 22.9% | 1.1% | 88.0% | 14.0 KB | ✅ 尺寸可容纳 |
| 加权 96×96 | 96×96 | 99.9% | 71.4% | 28.6% | 0.1% | 85.7% | 34.7 KB | ❌ 超限 |

**这张表的验证集只有 35 张 crop**，每错判 1 张就是 2.86 个百分点。
「误打 8/35 = 22.9%」的 **95% 置信区间是 [12.1%, 39.0%]，宽达 27 个百分点**。

所以：
- ❌ 「误打率 34.3% → 22.9%」—— CI 大幅重叠，**这个提升在统计上不成立**
- ❌ 「48×48 的 88.0% 优于 96×96 的 85.7%」—— 差距只有 **0.8 张样本**，纯属噪声
- ❌ 用这张表决定上哪颗芯片 —— 是拿噪声做决策

**唯一可信的数字是交叉验证结果**（见下方「可信评估」一节）。

### ✅ 可信评估：按原图分组的 K 折交叉验证

```bash
python _toolchain\cv_cls_int8.py --size 48 --folds 5 --epochs 40 --augment
```

两个关键改进：
1. **按原图 ID 分组** —— 贴图名 `latvia_00880_362_176.jpg` 前缀即原图 ID，
   同源贴图整体分到同一折，杜绝「训练时见过测试样本」的泄漏
2. **全量评估** —— train + val 合并，406 个 crop 样本每张恰好验证一次

**实测结果（int8 量化后，48×48 + 增广）：**

| 训练轮数 | 折间 std | 误打作物 | 漏打杂草 | 平衡准确率 | 判定 |
|---|---|---|---|---|---|
| 40 轮 | **10.7%** | 34.7% | 3.8% | 80.7% | ❌ 欠拟合 |
| **120 轮** | **1.8%** | **18.5%** | 4.3% | **88.6%** | ✅ 收敛，可用 |

> **先看折间 std，再看均值。** std > 5% 说明没收敛，均值毫无意义。

> ### 一个能骗过人的假象
> 40 轮那次的**误打作物率只有 2.2%**（单看某一折），看着比 120 轮的 18.5% 好得多。
> 但那是因为模型**几乎把所有东西都判成了 weed** —— 漏打率仅 2.2%，
> 意味着它几乎不开枪。**误打率必须与漏打率、平衡准确率、折间 std 一起看。**

> 相比之下，原验证集（35 张 crop）报出的 22.9% 是**高估**，
> 原因是那 35 张恰好偏难。真实水平介于两者之间，**以交叉验证的 18.5% 为准**。
> 置信区间宽度从 27 个百分点降到 7.5 个百分点。

### 部署选型（基于尺寸而非精度）

| 平台 | 选谁 | 依据 |
|---|---|---|
| **STM32F103C8T6** | `weed_cls_c8_int8`（48×48） | 峰值张量 9.2 KB ≤ 20K SRAM |
| 资源充裕的平台 | `weed_cls_int8`（96×96） | 峰值张量 144 KB，需大内存 |

>尺寸选择依据是**内存占用**，不是精度。48×96 在精度上的差异落在噪声内，
> 但 96×96 的峰值张量会直接撑爆 C8T6。

### 复现

```bash
python tools_crop_cls.py                # 按检测框裁 96x96 贴图
python _toolchain/train_cls_int8_balanced.py --size 48 --out weed_cls_c8_int8
python _toolchain/train_cls_int8_balanced.py --size 96 --out weed_cls_int8
python _toolchain/eval_cls_int8.py --model models/weed_cls_c8_int8.tflite   # 逐类评估
```

> 评估一定要看**逐类**指标。整体准确率 98% 在 30:1 失衡数据上没有意义。

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
| **[部署手册](docs/部署手册.md)** | ⭐ **从训练到模型上板全链路**：模型选型、类别失衡踩坑、C 符号名契约、故障速查 |
| **[烧录指南](docs/烧录指南.md)** | ⭐ **STM32F407 固件烧录**：驱动安装、备份、镜像选择、故障排查 |
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
3. **int8 分类模型**：已用新数据集重训，见上文「int8 分类模型」章节。C8T6 上用 `weed_cls_c8_int8`（48×48）—— 依据是**峰值张量 9.2 KB 能塞进 20K SRAM**，不是精度（两者精度差异落在噪声内）。

---

## 📄 许可证

仅供学习与研究使用。

## 🙏 致谢

- [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)
- 数据集：[Project-AgML/crop_weed_detection_latvia](https://huggingface.co/datasets/Project-AgML/crop_weed_detection_latvia)