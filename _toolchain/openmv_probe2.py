# -*- coding: utf-8 -*-
"""一次性抓全：色块密度/ROI 色彩统计/文件落盘情况，然后恢复 main.py。"""
import time

import serial

s = serial.Serial("COM4", 115200, timeout=0.4)
time.sleep(0.3)


def cmd(code, wait=1.5):
    s.write(code.encode() + b"\r")
    time.sleep(wait)
    return s.read(4096).decode("utf-8", "replace").replace("\r", "")


s.write(b"\x03\x03")
time.sleep(0.8)
s.reset_input_buffer()
print("[中断] 主循环已停\n")

print(cmd("import sensor, image, time, os"))
print(cmd("sensor.reset(); sensor.set_pixformat(sensor.RGB565); "
          "sensor.set_framesize(sensor.QVGA); sensor.skip_frames(time=1200); "
          "print('INIT_OK')", 3.0))

# 全画面色彩统计（判断场景里到底有没有绿色）
print(cmd("img=sensor.snapshot(); st=img.get_statistics(); "
          "print('FULL L', st.l_min(), st.l_mean(), st.l_max(), "
          "'A', st.a_min(), st.a_mean(), st.a_max(), "
          "'B', st.b_min(), st.b_mean(), st.b_max())", 2.5))

# 逐色块细节：密度、ROI 内平均色
print(cmd("bl=img.find_blobs([(0,55,-30,40,-10,60)], pixels_threshold=120, "
          "area_threshold=120, merge=True); "
          "print('N', len(bl))", 2.0))
print(cmd("print('DETAIL', [(b.cx(), b.cy(), b.w(), b.h(), b.pixels(), "
          "round(b.density(),3)) for b in bl[:6]])", 2.0))
print(cmd("print('ROI_LAB', [(st2.l_mean(), st2.a_mean(), st2.b_mean()) "
          "for st2 in [img.get_statistics(roi=b.rect()) for b in bl[:4]]])", 2.5))

# 绿色专门测一次（B 通道正值 = 偏黄绿）
print(cmd("g=img.find_blobs([(20,90,-40,-5,10,70)], pixels_threshold=200, "
          "area_threshold=200, merge=True); print('GREEN_BLOBS', len(g), "
          "[(b.cx(),b.cy(),b.pixels()) for b in g[:4]])", 2.5))

# 落盘并读回大小
print(cmd("img.save('/flash/snap_now.jpg', quality=70); "
          "print('SIZE', os.stat('/flash/snap_now.jpg')[6])", 2.5))
print(cmd("print('FREEMEM', __import__('gc').mem_free())", 1.5))

# 恢复
print(cmd("import sys; sys.path.insert(0,'/flash'); "
          "exec(open('/flash/main.py').read())", 4.0))
s.close()
print("\n[恢复] main.py 已重启")
