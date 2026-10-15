# 🌿 植物病害智能检测系统

## 📋 项目简介

基于 YOLOv8 的植物病害检测系统，支持：
- ✅ 10类植物病害识别（番茄、草莓、南瓜、玉米、土豆等）
- ✅ 图形界面操作
- ✅ 摄像头实时检测
- ✅ 独立部署（ONNX格式）

## 🚀 快速开始

### 1. 启动系统

双击运行：
```
E:\PlantDiseaseProject\start.bat
```

### 2. 完整使用流程

```
[1] 准备数据集
    ↓
[2] 安装PyTorch (CUDA 11.3)
    ↓
[3] 训练模型
    ↓
[4] 使用GUI检测
    ↓
[5] 导出ONNX部署
```

## 📁 项目结构

```
E:\PlantDiseaseProject\
├── 📁 datasets\plantvillage_yolo\  # 数据集
│   ├── 📁 train\images\           # 训练图片
│   ├── 📁 train\labels\           # 训练标注
│   ├── 📁 val\images\             # 验证图片
│   └── data.yaml                   # 数据集配置
├── 📁 models\                       # 训练好的模型
├── 📁 gui\                         # GUI程序
│   └── plant_disease_gui.py
├── 📁 export\                      # 导出模型
├── 📄 train.py                     # 训练脚本
├── 📄 export_onnx.py               # ONNX导出
├── 📄 onnx_inference.py            # ONNX推理
├── 📄 start.bat                   # 启动器
├── 📄 README.md                    # 说明文档
├── 📄 数据集下载指南.md
├── 📄 训练指南.md
└── 📄 模型优化指南.md
```

## 📊 功能模块

### 1️⃣ 数据准备
- 数据集：PlantVillage（54,000+图片，38类病害）
- 格式：YOLO格式（已标注）
- 下载：https://www.kaggle.com/datasets/sebastianpalaciob/plantvillage-for-object-detection-yolo

### 2️⃣ 模型训练
- 框架：YOLOv8
- 环境：CUDA 11.3 + PyTorch 2.0.1
- 参数：
  - epochs: 50-100
  - batch: 8 (RTX 5060)
  - imgsz: 640
  - device: GPU (CUDA)

### 3️⃣ 模型优化
- 评估指标：mAP、Precision、Recall、F1
- 调优技巧：数据增强、学习率调整、类别平衡
- 诊断工具：自动分析训练结果

### 4️⃣ GUI界面
- 功能：图片选择识别、摄像头实时检测
- 显示：边界框、类别标签、置信度
- 操作：保存结果、调整参数

### 5️⃣ ONNX部署
- 格式：ONNX (独立于YOLOv8)
- 推理：纯OpenCV
- 平台：Windows/Linux/工控机

## 💻 使用方法

### 训练模型
```bash
cd E:\PlantDiseaseProject
python train.py --epochs 50 --batch 8 --imgsz 640
```

### 使用GUI
```bash
python gui\plant_disease_gui.py
```

### 导出ONNX
```bash
python export_onnx.py --model models\plant_disease_exp1\weights\best.pt
```

### ONNX推理
```bash
# 单张图片
python onnx_inference.py --model export\plant_disease.onnx --image test.jpg

# 摄像头
python onnx_inference.py --model export\plant_disease.onnx --camera

# 批量处理
python onnx_inference.py --model export\plant_disease.onnx --folder test_images/
```

## 🎯 病害类别

| 类别 | 名称 | 说明 |
|------|------|------|
| 0 | 番茄早疫病 | Early Blight |
| 1 | 番茄晚疫病 | Late Blight |
| 2 | 番茄叶霉病 | Leaf Mold |
| 3 | 番茄斑点病 | Septoria Spot |
| 4 | 番茄黄化病毒 | Yellow Virus |
| 5 | 草莓叶枯病 | Strawberry Scorch |
| 6 | 南瓜白粉病 | Powdery Mildew |
| 7 | 玉米叶斑病 | Gray Leaf Spot |
| 8 | 土豆晚疫病 | Potato Late Blight |
| 9 | 健康叶片 | Healthy |

## 📈 性能指标

### 训练指标
- mAP50: 0.75-0.85 (目标)
- Precision: 0.80-0.90
- Recall: 0.75-0.85

### 推理速度
- GPU (RTX 5060): ~50-100ms/帧
- CPU: ~100-200ms/帧

## 🔧 系统要求

- Windows 11
- Python 3.11.9
- CUDA 11.3
- NVIDIA GPU (RTX 5060)

## 📚 文档

- [数据集下载指南](数据集下载指南.md)
- [训练指南](训练指南.md)
- [模型优化指南](模型优化指南.md)

## 📝 许可证

本项目仅供学习和研究使用。

## 🙏 致谢

- YOLOv8: https://github.com/ultralytics/ultralytics
- PlantVillage Dataset

---

**🎉 开始植物病害智能检测之旅！**
