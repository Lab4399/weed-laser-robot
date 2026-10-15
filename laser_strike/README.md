# 植物病虫害识别 + 激光瞄准打击系统

摄像头识别植物病虫害，自动驱动两轴激光云台，把激光打到病斑/虫害位置。
可选接 GOOD DOG 底盘，完成「**行走 → 识别 → 发射 → 完成**」一整套动作。

## 一、一套动作（行走 → 识别 → 发射 → 完成）

```bash
cd /e/PlantDiseaseProject/laser_strike

# 全仿真：打印狗行走/激光动作 + USB 摄像头识别
python mission.py --sim

# 仿真 + 单张图片识别
python mission.py --sim --source leaf.jpg

# 真机：GOOD DOG 底盘(COM4) + 激光云台(COM3)
python mission.py --dog-port COM4 --laser-port COM3
```

动作流程：

```
[1/4] 行走   GOOD DOG 前进（全电机同速）
[2/4] 识别   边前进边检测病虫害（YOLO / 颜色病斑），发现即停
[3/4] 发射   停止行走，激光开启 N 秒
[4/4] 完成   关激光 + 急停，收尾
```

GOOD DOG 控制帧（博特律动协议，以 `Core/Src/command.c` 为准，详见 `gooddog.py`）：

- 前进 500：`AA 06 FF 01 F4 A4`
- 停止：`AA 06 FF 00 00 AF`

## 二、持续瞄准模式（识别 → 视觉伺服瞄准 → 激光）

```bash
# 仿真 + USB 摄像头（打印云台/激光动作）
python main.py --sim

# 无模型演示：颜色病斑分割
python main.py --detector blob --sim

# 真机：接 Arduino 激光云台
python main.py --port COM3
```

按 `q` 退出。

## 三、接真机

1. **激光云台**：Arduino 烧录 `arduino/laser_gimbal.ino`（2 舵机 + 激光，见文件头接线）。
2. **行走底盘**：GOOD DOG（STM32F407）已含博特律动协议解析，用串口发帧即可，无需改固件。
3. 修改 `config.py`：`SERIAL_PORT`(激光) / `DOG_PORT`(狗) / 速度与超时等参数。
4. 运行上面真机命令。

## 四、依赖

- 基础：`opencv-python` `numpy`
- YOLO 模式：`ultralytics`（GPU 推荐用 WSL 内环境）
- 串口真机：`pyserial`

## 五、目录

```
laser_strike/
├─ mission.py       一套动作：行走→识别→发射→完成
├─ gooddog.py       GOOD DOG 底盘控制（博特律动协议）
├─ main.py          持续瞄准闭环（识别→瞄准→激光）
├─ config.py        配置（串口/速度/类别/激光安全参数）
├─ detector.py      识别（YOLO / 颜色病斑兜底）
├─ aiming.py        瞄准（视觉伺服：像素误差 -> 云台角度）
├─ actuator.py      执行器（串口 ASCII / 仿真）
├─ arduino/         Arduino 云台+激光固件
├─ 系统方案.md      总体方案与分阶段实施
└─ README.md        本文档
```

## 六、激光安全

- 只用低功率激光（≤5mW / Class 3R 及以下）。
- 禁止照射人、动物、反光面；工作区加挡板。
- 上电默认激光关闭、云台回中；异常用 `S` 指令或硬件急停。

> 详细方案与阶段规划见 `系统方案.md`。
