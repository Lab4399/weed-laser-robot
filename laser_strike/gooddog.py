# -*- coding: utf-8 -*-
"""GOOD DOG 底盘控制（博特律动协议，按 Core/Src/command.c 实际实现）

帧格式（以 command.c 为准，注意与 BUILD_GUIDE.md 的旧描述不同）：
  byte[0]     = 0xAA                帧头
  byte[1]     = L                   整帧总长度 = 2 + 数据组数*3 + 1(校验)
  byte[2..L-2]= 数据组              每组 3 字节 [MotorID][SpeedH][SpeedL]
  byte[L-1]   = 校验 = sum(byte[0..L-2]) & 0xFF

  MotorID: 1~4 对应电机 1~4；0xFF = 全部电机同速
  Speed: int16，-1000~1000（负=反转），大端

例：全部电机前进 500 -> AA 06 FF 01 F4 A4
    全部电机停止     -> AA 06 FF 00 00 AF
"""
import time
import config


def _clamp_speed(v):
    return max(-1000, min(1000, int(v)))


def make_frame(pairs):
    """生成一帧控制指令。pairs = [(motor_id, speed), ...]"""
    n = len(pairs)
    body = bytearray([0xAA, 2 + 3 * n + 1])  # 帧头 + 长度
    for mid, spd in pairs:
        u = _clamp_speed(spd) & 0xFFFF       # 负数转 16 位补码，避免算术右移出错
        body += bytes([mid & 0xFF, (u >> 8) & 0xFF, u & 0xFF])
    body.append(sum(body) & 0xFF)            # 累加校验（低 8 位）
    return bytes(body)


class BaseDog:
    def move(self, speed):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def set_motors(self, m1, m2, m3, m4):
        raise NotImplementedError

    def close(self):
        pass


class SimDog(BaseDog):
    """仿真：无硬件，仅打印动作"""

    def move(self, speed):
        print(f"[dog] 行走 speed={_clamp_speed(speed)}")

    def stop(self):
        print("[dog] 停止")

    def set_motors(self, m1, m2, m3, m4):
        print(f"[dog] 电机 -> {m1} {m2} {m3} {m4}")


class SerialDog(BaseDog):
    """串口版：向 STM32F407 发送博特律动帧"""

    def __init__(self, port=None, baud=None):
        import serial
        self.ser = serial.Serial(port or config.DOG_PORT,
                                 baud or config.DOG_BAUD, timeout=0.2)
        time.sleep(1)  # 等待上电
        self.stop()

    def _send(self, pairs):
        self.ser.write(make_frame(pairs))

    def move(self, speed):
        self._send([(0xFF, speed)])

    def stop(self):
        self._send([(0xFF, 0)])

    def set_motors(self, m1, m2, m3, m4):
        self._send([(1, m1), (2, m2), (3, m3), (4, m4)])

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def build_dog(sim=False, port=None):
    if sim:
        return SimDog()
    return SerialDog(port)
