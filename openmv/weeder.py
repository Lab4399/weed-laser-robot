# weeder.py —— 激光除杂草小车主闭环（运行在 OpenMV4 H7）
# 烧录：用 OpenMV IDE 把本文件存为 main.py 烧入，上电即跑。
#
# 一整套动作：
#   WALK(前进巡检) -> SCAN(识别杂草/病斑) -> AIM(云台转向对准) -> FIRE(激光开) -> DONE(完成)
#
# 说明：OpenMV 算力有限，端侧识别用 find_blobs（颜色/病斑）或模板匹配，
#       不跑 YOLOv8 实时推理。YOLOv8 专用模型在 PC 端训练/离线分析（见 weeder_host.py）。
#
# ===================== 接线（默认 local 模式，OpenMV 直接驱底盘） =====================
# 摄像头 ：OV7725 接 OpenMV 摄像头座
# 电机驱动（TB6612 / L298N，逻辑 5V 与 OpenMV 共地）：
#   左轮 IN1/IN2 -> P0 / P1     左轮 PWM -> P2 (TIM2_CH3)
#   右轮 IN1/IN2 -> P4 / P5     右轮 PWM -> P3 (TIM2_CH4)
# 舵机云台：pan -> P7 (Servo1)   tilt -> P8 (Servo2)
# 激光    ：P6 -> MOS/三极管 -> 激光模组（5V 经驱动，勿直连 IO）
#
# 注意：本固件不使用串口（避免与电机引脚 P4/P5 冲突）。调试时另烧 main.py 经 UART 发图给 PC。
# ====================================================================================

import sensor
import image
import time
import pyb
from pyb import Pin, Timer, Servo, LED

# ============================ 可调参数 ============================
FORWARD_SPEED = 60        # 前进占空比 0~100
SCAN_TIMEOUT  = 30.0      # 识别阶段最长秒数，超时视为未发现
LASER_HOLD    = 1.0       # 激光持续开启秒数
PAN_CENTER    = 90        # 云台水平归中角
TILT_CENTER   = 90        # 云台俯仰归中角
KP_PAN        = 0.25      # 像素误差 -> 舵机角度增量
DEADZONE_PX   = 15        # 对准死区（像素）
DETECT_MODE   = "lesion"  # "lesion"=病斑色块 / "weed"=杂草（需现场调阈值或用模板）

# 病斑/杂草颜色阈值（LAB 空间）。【必须按现场实测调整！】示例：
#   lesion：偏黄/褐的病斑（作物绿叶背景中找异常色）
#   weed  ：示例为"亮绿外的非绿"（仅占位，实际应用建议用模板匹配或作物行分割）
BLOB_THRESH = {
    "lesion": [(20, 90, 10, 70, 5, 55), (10, 70, -10, 30, 30, 80)],
    "weed":   [(30, 100, -20, 20, -20, 20)],
}
PIXELS_MIN = 300          # 最小像素数，过滤噪点
AREA_MIN   = 300          # 最小面积
# =====================================================================


class Car:
    """两轮底盘驱动（OpenMV 直接驱 TB6612/L298N）"""

    def __init__(self):
        self.in1 = Pin('P0', Pin.OUT)
        self.in2 = Pin('P1', Pin.OUT)
        self.in3 = Pin('P4', Pin.OUT)
        self.in4 = Pin('P5', Pin.OUT)
        self.tim = Timer(2, freq=1000)
        self.pwm_l = self.tim.channel(3, Timer.PWM, pin=Pin('P2'))
        self.pwm_r = self.tim.channel(4, Timer.PWM, pin=Pin('P3'))

    def _drive(self, pwm_l, pwm_r):
        pwm_l = max(-100, min(100, int(pwm_l)))
        pwm_r = max(-100, min(100, int(pwm_r)))
        self.in1.value(1 if pwm_l >= 0 else 0)
        self.in2.value(0 if pwm_l >= 0 else 1)
        self.in3.value(1 if pwm_r >= 0 else 0)
        self.in4.value(0 if pwm_r >= 0 else 1)
        self.pwm_l.pulse_width_percent(abs(pwm_l))
        self.pwm_r.pulse_width_percent(abs(pwm_r))

    def forward(self, s=FORWARD_SPEED):
        self._drive(s, s)

    def stop(self):
        self._drive(0, 0)

    def close(self):
        self.stop()


def detect_target(img, mode):
    """返回最大目标的 (cx, cy) 或 None。"""
    thresh = BLOB_THRESH.get(mode, BLOB_THRESH["lesion"])
    blobs = img.find_blobs(thresh, pixels_threshold=PIXELS_MIN,
                           area_threshold=AREA_MIN, merge=True)
    if not blobs:
        return None
    b = max(blobs, key=lambda x: x.area())
    return b.cx(), b.cy()


def run():
    # 摄像头初始化
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)   # 320x240
    sensor.skip_frames(2000)
    sensor.set_auto_gain(False)
    sensor.set_auto_whitebal(False)
    print("[weeder] 摄像头就绪")

    led = LED(1)
    car = Car()
    pan = Servo(1); pan.angle(PAN_CENTER)   # P7
    tilt = Servo(2); tilt.angle(TILT_CENTER)  # P8
    laser = Pin('P6', Pin.OUT, value=0)

    state = "SCAN"
    pan_a = PAN_CENTER
    car.forward(FORWARD_SPEED)        # 一上来就前进巡检
    t0 = time.ticks_ms()
    print("[weeder] 开始：行走 -> 识别 -> 发射 -> 完成")

    while True:
        img = sensor.snapshot()
        led.on()

        if state == "SCAN":
            tgt = detect_target(img, DETECT_MODE)
            if tgt:
                car.stop()
                print("[weeder] 识别到目标，转入瞄准")
                state = "AIM"
            elif time.ticks_diff(time.ticks_ms(), t0) / 1000.0 > SCAN_TIMEOUT:
                car.stop()
                print("[weeder] 超时未发现目标，结束")
                break

        elif state == "AIM":
            tgt = detect_target(img, DETECT_MODE)
            if not tgt:
                car.forward(FORWARD_SPEED)   # 目标丢了，继续走
                state = "SCAN"
                t0 = time.ticks_ms()
                continue
            cx, cy = tgt
            err = cx - img.width() // 2
            pan_a = max(0, min(180, pan_a - err * KP_PAN))
            pan.angle(int(pan_a))
            if abs(err) < DEADZONE_PX:
                print("[weeder] 已对准，转入发射")
                state = "FIRE"

        elif state == "FIRE":
            laser.value(1)
            time.sleep_ms(int(LASER_HOLD * 1000))
            laser.value(0)
            print("[weeder] 激光发射完成，转入完成")
            state = "DONE"

        elif state == "DONE":
            car.stop()
            laser.value(0)
            led.off()
            print("[weeder] 完成整套动作")
            break

        led.off()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("[weeder] 异常:", e)
