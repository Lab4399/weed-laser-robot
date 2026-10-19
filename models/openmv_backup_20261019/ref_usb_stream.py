# OpenMV 端代码：USB 虚拟串口(USB_VCP) JPEG 上传 —— 适配 OpenMV USB 直插电脑
# 用法：把本文件改名为 main.py 后用 OpenMV IDE 烧录到摄像头
# 协议同 UART 版：[0-3]图像长度(小端) | [4-7]帧计数(小端) | [8..]JPEG
import sensor
import image
import time
from pyb import USB_VCP

SENSOR_W = 320
SENSOR_H = 240
JPEG_QUALITY = 85
FPS = 5

sensor.reset()
sensor.set_pixformat(sensor.RGB565)
sensor.set_framesize(sensor.QVGA)  # 320x240
sensor.skip_frames(100)
sensor.set_auto_gain(False)
sensor.set_auto_whitebal(False)
sensor.set_auto_exposure(False)

vcp = USB_VCP()  # OpenMV USB 数据口（PC 端表现为一个 COM）
print("[OpenMV] USB_VCP 就绪")
vcp.write(b"OPENMV_READY\n")

frame_count = 0
start = time.ticks_ms()
while True:
    try:
        img = sensor.snapshot()
        img.compress(quality=JPEG_QUALITY)   # OpenMV: compress() 就地压缩为 JPEG
        n = img.size()
        head = n.to_bytes(4, 'little') + frame_count.to_bytes(4, 'little')
        vcp.write(head)
        vcp.write(img)                        # image 对象支持 buffer 协议，可直接发送
        frame_count += 1
        if time.ticks_diff(time.ticks_ms(), start) >= 1000:
            print("[OpenMV] fps 约", frame_count)
            frame_count = 0
            start = time.ticks_ms()
        time.sleep_ms(int(1000 / FPS))
    except Exception as e:
        print("[OpenMV] err", e)
        time.sleep_ms(100)
