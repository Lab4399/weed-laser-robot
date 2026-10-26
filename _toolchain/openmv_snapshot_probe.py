# -*- coding: utf-8 -*-
"""OpenMV 快照抓取 + LAB 统计 + 恢复 main.py 运行。

注意：MicroPython REPL 不吃多行粘贴，所有命令必须是单行（分号连接，不用 if/for）。
"""
import sys
import time

import serial

PORT, BAUD = "COM4", 115200


def open_port():
    s = serial.Serial(PORT, BAUD, timeout=0.4)
    time.sleep(0.3)
    return s


def drain(s, sec=0.6):
    s.reset_input_buffer()
    t0 = time.time()
    while time.time() - t0 < sec:
        s.read(4096)


def cmd(s, code, wait=1.5):
    s.write(code.encode() + b"\r")
    time.sleep(wait)
    return s.read(4096).decode("utf-8", "replace").replace("\r", "")


def main():
    s = open_port()

    # 1. 中断当前脚本
    s.write(b"\x03\x03")
    time.sleep(0.8)
    drain(s, 0.5)
    print("[1] 已中断主循环")

    # 2. 重新初始化 sensor（清掉 Frame buffer error）
    print(cmd(s, "import sensor, image, time"))
    print(cmd(s, "sensor.reset(); sensor.set_pixformat(sensor.RGB565); "
                 "sensor.set_framesize(sensor.QVGA); sensor.skip_frames(time=1200); "
                 "print('INIT_OK', sensor.width(), sensor.height())", 3.0))

    # 3. LAB 统计
    print(cmd(s, "img=sensor.snapshot(); st=img.get_statistics(); "
                 "print('LAB', st.l_min(), st.l_mean(), st.l_max(), "
                 "st.a_min(), st.a_mean(), st.a_max(), "
                 "st.b_min(), st.b_mean(), st.b_max())", 2.5))

    # 4. 用当前阈值找色块
    print(cmd(s, "bl=img.find_blobs([(0,55,-30,40,-10,60)], pixels_threshold=120, "
                 "area_threshold=120, merge=True); "
                 "print('BLOBS', len(bl), [(b.cx(), b.cy(), b.pixels()) for b in bl[:5]])", 2.5))

    # 5. 存图
    print(cmd(s, "img.save('/flash/snap_now.jpg', quality=70); print('SAVED')", 2.5))

    # 6. 恢复 main.py
    print(cmd(s, "import sys; sys.path.insert(0,'/flash'); "
                 "exec(open('/flash/main.py').read())", 4.0))
    s.close()
    print("[6] 已重新启动 main.py")


if __name__ == "__main__":
    sys.exit(main())
