# 🎥 OpenMV 集成完整指南

## 📋 文件清单

### OpenMV端代码
- **文件**: `openmv\main.py`
- **功能**: 拍摄JPEG并通过串口发送到PC

### PC端GUI代码
- **文件**: `gui\plant_disease_gui_openmv.py`
- **功能**: 接收串口数据，实时检测，显示结果

### 启动脚本
- **文件**: `启动OpenMV版GUI.bat`
- **功能**: 一键启动OpenMV集成版GUI

---

## 🔧 使用步骤

### 第一步：OpenMV端准备

1. **连接OpenMV**
   - 用USB线将OpenMV连接到电脑
   - 打开OpenMV IDE

2. **烧录代码**
   ```
   文件 ->打开 -> 选择 E:\PlantDiseaseProject\openmv\main.py
   工具 -> 保存到OpenMV (作为main.py)
   ```

3. **验证运行**
   - 在OpenMV IDE中点击"运行"按钮
   - 查看终端输出：应显示"[OpenMV] 等待 PC 连接..."

### 第二步：PC端准备

1. **安装依赖**
   ```bash
   pip install pyserial ultralytics opencv-python pillow
   ```

2. **准备模型**
   - 训练好的模型: `models\best.pt`
   - 如果没有，GUI仍可运行（仅显示图像）

### 第三步：启动检测

**方式1：双击启动脚本**
```
双击: E:\PlantDiseaseProject\启动OpenMV版GUI.bat
```

**方式2：命令行**
```bash
cd E:\PlantDiseaseProject
python gui\plant_disease_gui_openmv.py
```

### 第四步：使用OpenMV模式

1. 在GUI界面选择"OpenMV模式"
2. 确认串口号（通常自动检测）
3. 点击"启动OpenMV检测"
4. 等待连接并开始接收图像

---

## 📡 串口通信协议

### 数据包格式

```
[0-3]:  4字节  - 图像长度（小端序）
[4-7]:  4字节  - 帧计数（小端序）
[8...]: N字节 - JPEG图像数据
```

### 波特率
- **115200 bps**

### 帧率
- **约 2-5 fps**（取决于图像大小和PC处理能力）

---

## 🎯 功能说明

### OpenMV端功能
- ✅ 自动初始化摄像头
- ✅ JPEG压缩（质量85）
- ✅ 串口发送（带长度头）
- ✅ 帧率控制
- ✅ 错误处理

### PC端功能
- ✅ 自动检测串口
- ✅ 协议解析（长度+数据）
- ✅ JPEG解码
- ✅ YOLO模型推理
- ✅ 结果可视化
- ✅ 病害建议显示

---

## 🆘 常见问题

### Q1: OpenMV无法连接
**A**: 
- 检查USB线是否连接正确
- 在设备管理器中查看COM口号
- 手动选择正确的串口号

### Q2: 图像显示不出来
**A**:
- 检查波特率是否一致（115200）
- 查看OpenMV终端输出
- 检查数据包长度是否正确

### Q3: 检测速度慢
**A**:
- 降低图像分辨率（QVGA→QQVGA）
- 降低JPEG质量（85→70）
- 使用更小的YOLO模型（n→s）

### Q4: 模型未加载
**A**:
- 先训练模型：`python train.py`
- 确认模型路径：`models\best.pt`
- GUI仍可运行，仅显示图像

---

## 📊 性能参考

| 配置 | 帧率 | 延迟 |
|------|------|------|
| QVGA (320x240) | 3-5 fps | ~200ms |
| QQVGA (160x120) | 5-8 fps | ~100ms |
| VGA (640x480) | 1-2 fps | ~500ms |

---

## 🔗 相关文件

| 文件 | 路径 |
|------|------|
| OpenMV代码 | `E:\PlantDiseaseProject\openmv\main.py` |
| GUI代码 | `E:\PlantDiseaseProject\gui\plant_disease_gui_openmv.py` |
| 启动脚本 | `E:\PlantDiseaseProject\启动OpenMV版GUI.bat` |

---

## ✅ 检查清单

- [ ] OpenMV已烧录main.py
- [ ] USB线连接正确
- [ ] 串口驱动已安装
- [ ] pyserial已安装 (`pip install pyserial`)
- [ ] 模型文件已准备（可选）
- [ ] GUI程序可正常启动

---

**🎉 OpenMV集成完成，开始实时检测吧！**
