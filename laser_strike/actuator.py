# -*- coding: utf-8 -*-
"""执行器：云台舵机 + 激光。串口版(ASCII 协议) / 仿真版(仅打印)"""
import time
import config


class BaseActuator:
    def set_angles(self, pan, tilt):
        raise NotImplementedError

    def laser(self, on):
        raise NotImplementedError

    def estop(self):
        raise NotImplementedError

    def close(self):
        pass


class SimActuator(BaseActuator):
    """仿真：无硬件，仅打印动作"""

    def __init__(self):
        self.pan = config.PAN_INIT
        self.tilt = config.TILT_INIT
        self.laser_on = False

    def set_angles(self, pan, tilt):
        self.pan = int(pan)
        self.tilt = int(tilt)
        print(f"[actuator] 云台 -> pan={self.pan} tilt={self.tilt}")

    def laser(self, on):
        self.laser_on = bool(on)
        print(f"[actuator] 激光 -> {'开' if on else '关'}")

    def estop(self):
        self.laser(False)
        self.set_angles(config.PAN_INIT, config.TILT_INIT)
        print("[actuator] 急停")


class SerialActuator(BaseActuator):
    """串口版：ASCII 协议，每行一条，\\n 结尾
       P<pan>  T<tilt>  L1/L0  S(急停)
    """

    def __init__(self, port=None, baud=None):
        import serial
        self.ser = serial.Serial(port or config.SERIAL_PORT,
                                 baud or config.SERIAL_BAUD, timeout=0.2)
        time.sleep(2)  # 等待 Arduino 复位
        self.pan = config.PAN_INIT
        self.tilt = config.TILT_INIT
        self.laser_on = False

    def _send(self, s):
        self.ser.write((s + "\n").encode())

    def set_angles(self, pan, tilt):
        self.pan = int(max(config.PAN_MIN, min(config.PAN_MAX, pan)))
        self.tilt = int(max(config.TILT_MIN, min(config.TILT_MAX, tilt)))
        self._send(f"P{self.pan}")
        self._send(f"T{self.tilt}")

    def laser(self, on):
        self.laser_on = bool(on)
        self._send("L1" if on else "L0")

    def estop(self):
        self._send("S")
        self.laser_on = False

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def build_actuator(sim=False, port=None):
    if sim:
        return SimActuator()
    return SerialActuator(port)
