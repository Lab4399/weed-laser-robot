# -*- coding: utf-8 -*-
r"""
check_openmv_link.py —— OpenMV ⇄ PC 通信链路体检

在跑激光之前，先确认「看得见」这一环是通的。故障分三层，逐层排除：

    第 1 层  串口能打开吗          → PermissionError = IDE 占用 / 端口号错
    第 2 层  有数据流过来吗        → 超时 = OpenMV 脚本没烧 / 线接触不良 / 波特率不符
    第 3 层  能解出完整 JPEG 吗    → 协议错位 = 长度头解析异常

用法
----
    # 1) 关闭 OpenMV IDE（它会独占串口），然后：
    python _toolchain\check_openmv_link.py --port COM4

    # 2) 或者只检查有哪些串口：
    python _toolchain\check_openmv_link.py --list

注意
----
OpenMV IDE 与本脚本**不能同时**占用同一个串口。IDE 在跑 helloworld.py 时
会独占 COM4，此时本脚本必然报 PermissionError(13)。这是正常的，不是 bug。
"""

import argparse
import os
import time

import serial
import serial.tools.list_ports

PROJ = r"E:\PlantDiseaseProject"


def hr(t):
    print("\n" + "=" * 66)
    print(f"  {t}")
    print("=" * 66)


def list_ports():
    hr("串口清单")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("  没有检测到任何串口")
        print("  → 检查 USB 线是否插好、是否需要换一根数据线（有些线只供电不通信）")
        return
    print(f"  {'端口':<8}{'描述':<32}{'VID':>6}{'PID':>6}")
    for p in ports:
        print(f"  {p.device:<8}{(p.description or '')[:30]:<32}"
              f"{(p.vid or 0):>6}{(p.pid or 0):>6}")
    print()
    print("  OpenMV Cam H7 通常显示为 'USB 串行设备'，VID=14277(0x37C5)")
    print("  若列表为空但 IDE 能连上 → 可能是 IDE 独占了端口，重开本脚本试试")


def try_open(port, baud=115200, wait=2.0):
    hr(f"第 1 层：打开 {port} @ {baud}")
    print("  正在打开 ...")
    try:
        s = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        if isinstance(e.args[1] if len(e.args) > 1 else None, PermissionError) \
                or '拒绝访问' in str(e):
            print("  ❌ PermissionError：端口被占用")
            print("     最可能的原因：**OpenMV IDE 正开着并连着这个口**")
            print("     处理：关掉 IDE 的串口连接（或完全退出 IDE），再重跑本脚本")
        else:
            print(f"  ❌ 打不开：{e}")
            print("     检查：端口号是否正确 / USB 线是否为数据线")
        return None
    except Exception as e:
        print(f"  ❌ 异常：{e}")
        return None

    print(f"  ✅ 端口已打开：{s.name}")
    print(f"     波特率 {s.baud}  超时 {s.timeout}s")
    # 等 OpenMV 的启动横幅
    s.reset_input_buffer()
    s.write(b"\n")          # 敲一下，看有没有回显
    time.sleep(wait)
    banner = s.read(512)
    if banner:
        txt = banner.decode('utf-8', errors='replace')
        print(f"  ✅ 收到 OpenMV 回显 {len(banner)} 字节：")
        for line in txt.strip().splitlines()[:5]:
            print(f"       {line}")
    else:
        print("  ℹ️  12 秒内无回显（IDE 脚本里print 的内容可能没接上，不一定是故障）")
    return s


def check_stream(s, seconds=12, jpeg_hdr=b'\xff\xd8'):
    """第 2+3 层：按 openmv/main.py 的协议解析
       [0-3] 长度LE  [4-7] 帧号LE  [8...] JPEG"""
    hr(f"第 2 层：接收数据流（最多等 {seconds} 秒）")
    print("  协议：4B长度(LE) + 4B帧号(LE) + JPEG")
    print("  前提：OpenMV 上必须已烧录 openmv/main.py 并在运行\n")

    s.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    frames = 0
    bad = 0

    while time.time() - t0 < seconds:
        d = s.read(8192)
        if not d:
            continue
        buf += d

        # 循环解析出所有完整帧
        while len(buf) >= 8:
            n = int.from_bytes(buf[0:4], 'little')
            fid = int.from_bytes(buf[4:8], 'little')
            # JPEG 长度不可能是 0 或离谱大
            if n == 0 or n > 200000:
                bad += 1
                if bad > 50:
                    print("  ❌ 连续出现 50 次非法长度，判定协议错位（检查两端脚本是否一致）")
                    return None
                # 尝试重新同步：找 JPEG 头
                idx = buf.find(jpeg_hdr)
                if idx > 0:
                    del buf[:idx]
                else:
                    del buf[:1]
                continue
            if len(buf) < 8 + n:
                break
            data = bytes(buf[8:8 + n])
            ok = data[:2] == jpeg_hdr
            frames += 1
            print(f"  {'✅' if ok else '❌'} 帧 #{fid}: {n} 字节"
                  f"  JPEG 头 {data[:2].hex()}"
                  f"  已收 {len(buf)}/{8+n}")
            if ok and frames == 1:
                p = os.path.join(PROJ, 'export', 'openmv_frame.jpg')
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as f:
                    f.write(data)
                print(f"     已保存首帧 -> {p}")
                print("     用图片查看器打开确认画面是否正常")
            del buf[:8 + n]

    hr("体检结果")
    if frames > 0:
        print(f"  ✅ 收到 {frames} 帧，链路正常")
        print("  可以进入下一步：接云台（laser_strike/actuator.py）")
        return True
    print(f"  ❌ {seconds} 秒内没有收到任何完整帧")
    print()
    print("  按可能性排序排查：")
    print("   1. OpenMV 上跑的还是 helloworld.py —— 要烧录 openmv/main.py")
    print("   2. 烧录后没点运行（IDE 左下角绿三角）")
    print("   3. UART 引脚接错：代码用 UART(3) = P4(TX) / P5(RX)，")
    print("      必须 P4 → PC 侧 RX，GND 必须共地")
    print("   4. PC 侧 RX/TX 接反了")
    print("   5. 波特率不是 115200")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='COM4')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--seconds', type=int, default=12)
    ap.add_argument('--list', action='store_true', help='只列串口')
    a = ap.parse_args()

    print("OpenMV ⇄ PC 链路体检")
    print(f"（前提：openmv/main.py 已烧录到摄像头并点运行）")

    if a.list:
        list_ports()
        return

    s = try_open(a.port, a.baud)
    if s is None:
        print()
        print("提示：加 --list 可以确认端口号")
        return
    try:
        check_stream(s, a.seconds)
    finally:
        s.close()
        print("\n串口已关闭")


if __name__ == '__main__':
    main()