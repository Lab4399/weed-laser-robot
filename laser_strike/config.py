# -*- coding: utf-8 -*-
"""激光瞄准打击系统 —— 全局配置"""

# ==================== 识别 ====================
# 杂草检测模型（YOLOv8n，训练自 datasets/weed_yolo）
# 产物 models/best.pt，由 models/weed_det/weights/best.pt 复制而来（见 train_weed.py）
# 注意：.pt 是 PyTorch 权重，只能在 PC 端 Python 跑（laser_strike/ 这一层）。
#      单片机端不能用 .pt，必须用 models/*.cc + *.h（C 数组，见 README「模型格式说明」）。
MODEL_PATH = r"E:\PlantDiseaseProject\models\best.pt"
# 兜底模型：YOLOv8n 通用检测（COCO，用于演示"检测→瞄准→激光"闭环，不区分作物/杂草）
FALLBACK_MODEL = r"E:\YOLOv8_Projects\models\yolov8n.pt"
CONF_THRES = 0.25
IOU_THRES = 0.45
IMG_SIZE = 640

# 杂草检测：crop + weed 二类
# 0 = crop（作物，不打）；1 = weed（杂草，打击目标）
# 注意：类别顺序由数据集决定，HuggingFace 原始 parquet 是 0=weed/1=crop，
#      parquet2yolo.py 里通过 HF2OURS 做了重映射才对上这里。
CLASS_NAMES = {0: "crop", 1: "weed"}
# 只打击杂草 weed(class=1)，绝不打击作物 crop(class=0)
TARGET_CLASSES = [1]

# ==================== 图像 / 瞄准 ====================
FRAME_W = 640
FRAME_H = 480
KP_PAN = 0.06      # 水平：像素误差 -> 角度增量（符号可调，反转方向）
KP_TILT = 0.06     # 俯仰：像素误差 -> 角度增量
DEADZONE_PX = 15   # 死区（像素）：误差小于此值视为已瞄准
MAX_STEP_DEG = 8   # 单帧最大角度增量（限幅防抖）
PAN_INIT = 90      # 云台初始角度
TILT_INIT = 90
PAN_MIN, PAN_MAX = 0, 180
TILT_MIN, TILT_MAX = 0, 180

# ==================== 激光 ====================
LASER_HOLD_SEC = 1.0      # 命中后激光持续开启时长
LASER_COOLDOWN_SEC = 2.0  # 两次射击最小间隔（防连续误射）

# ==================== 执行器串口（激光云台 Arduino） ====================
SERIAL_PORT = "COM3"
SERIAL_BAUD = 115200

# ==================== GOOD DOG 底盘串口（行走） ====================
DOG_PORT = "COM4"
DOG_BAUD = 115200
DOG_FORWARD_SPEED = 500    # 行走速度（-1000~1000，负=后退）
SCAN_TIMEOUT_SEC = 15.0    # 识别阶段最长时长，超时视为未发现目标
