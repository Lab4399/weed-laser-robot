# OpenMV 端代码：拍摄 JPEG 并通过串口发送到 PC
# 保存为 main.py，通过 OpenMV IDE 烧录到摄像头

import sensor
import image
import time
from pyb import UART

# ========== 配置参数 ==========
SENSOR_WIDTH = 320
SENSOR_HEIGHT = 240
JPEG_QUALITY = 85
FRAME_RATE = 5  # 帧率 (fps)

# ========== 初始化摄像头 ==========
sensor.reset()
sensor.set_pixformat(sensor.RGB565)  # 彩色模式
sensor.set_framesize(sensor.QVGA)    # 320x240
sensor.skip_frames(100)              # 预热

# 关闭自动增益和白平衡（提高稳定性）
sensor.set_auto_gain(False)
sensor.set_auto_whitebal(False)
sensor.set_auto_exposure(False)

print("[OpenMV] 摄像头初始化完成")
print(f"[OpenMV] 分辨率: {SENSOR_WIDTH}x{SENSOR_HEIGHT}")

# ========== 初始化串口 ==========
# UART(3) 使用 P4(TX) 和 P5(RX)
uart = UART(3, 115200, timeout_char=1000)

print("[OpenMV] 串口初始化完成 (波特率: 115200)")
print("[OpenMV] 等待 PC 连接...")

# 发送启动信号
uart.write(b"OPENMV_READY\n")

# ========== 主循环 ==========
frame_count = 0
start_time = time.ticks_ms()

while True:
    try:
        # 拍照
        img = sensor.snapshot()
        
        # 压缩为 JPEG
        img_data = img.compressed(quality=JPEG_QUALITY)
        jpeg_bytes = img_data.bytearray()
        
        # 获取图像长度
        length = len(jpeg_bytes)
        
        # 发送协议：
        # [0-3]: 4字节图像长度 (小端序)
        # [4-7]: 4字节帧计数 (小端序)
        # [8...]: JPEG数据
        
        # 打包长度和帧计数
        length_bytes = length.to_bytes(4, 'little')
        frame_bytes = frame_count.to_bytes(4, 'little')
        
        # 发送数据包
        uart.write(length_bytes)    # 4字节：图像长度
        uart.write(frame_bytes)      # 4字节：帧计数
        uart.write(jpeg_bytes)       # JPEG图像数据
        
        # 帧率控制
        frame_count += 1
        elapsed = time.ticks_diff(time.ticks_ms(), start_time) / 1000
        if elapsed >= 1.0:
            actual_fps = frame_count / elapsed
            print(f"[OpenMV] FPS: {actual_fps:.1f}, 发送: {length} bytes")
            frame_count = 0
            start_time = time.ticks_ms()
        
        # 控制发送频率
        time.sleep_ms(int(1000 / FRAME_RATE))
        
    except Exception as e:
        print(f"[OpenMV] 错误: {e}")
        time.sleep_ms(100)
