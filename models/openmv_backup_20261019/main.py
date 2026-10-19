# =============================================================================
#  weeder.py —— 智除草小车 OpenMV 端主控固件（架构 C / 感知端 + 打击决策）
# =============================================================================
#  ★ 本文件是 G 盘 main.py 的**源码版本**，两者内容必须一致。
#    G 盘那份是烧录产物（芯片上电自动执行），本文件是 PC 侧维护的源。
#    改动请改这里，然后复制到 G 盘根目录。
#
#  协议依据：laser_strike/接口与通信协议.md 第 8 节（V1.1 定版 2026-09-13）
#            对端固件：Hello-World/Core/Src/openmv_link.c（已编译入库）
#  历史：初版 weeder.py 已归档至
#        E:\PlantDiseaseProject\archive\openmv_weeder_before_2026-10-07\weeder.py
#
#  烧录：把本文件复制为 G 盘根目录 main.py，OpenMV 上电即自动运行。
#
#  职责划分（已由《整体架构_冻结版_V1.0》与《UART协议推进方案_2026-09-26》定案）：
#    本文件（OpenMV，STM32H743）  —— 采图、识别、视觉伺服、决定何时申请开火
#    F407（C:\Users\lenovo\Hello-World）—— 舵机执行、激光驱动、**安全闸**
#    L298N 底盘行走               —— 归 F407，本文件**不碰电机**
#
#  ★ 与初版 weeder.py 的区别（初版三处真实缺陷，均已修）
#    1) 初版在 FIRE 后 `time.sleep_ms((LASER_HOLD_MS + COOLDOWN)*1000)`
#       阻塞约 2.8 秒。期间主循环完全失能、不发任何帧 → 超过 F407 的
#       OPENMV_LINK_WATCHDOG_MS(1500ms) → F407 强制 pan 停 + 关激光。
#       即初版每次点射都会把自己关进看门狗。本版全程非阻塞，且保证任何
#       状态下距上次发送 < 1.4s，持续喂看门狗。
#    2) 初版异常兜底写的是 `GimbalLink().estop()` —— 新建了**第二个 UART3
#       实例**。MicroPython 上这很可能初始化失败或破坏已工作的实例，
#       导致急停根本发不出去。本版用模块级 _ACTIVE_LINK 登记实例复用。
#    3) 初版无任何发射次数约束，目标一直锁着就会 SCAN→AIM→FIRE 无限循环
#       打同一点，且不验证目标是否真被清除。本版补单目标/每分钟/总预算
#       三道熔断，并做目标面积合理性校验与端侧类别过滤（协议 §8.4 第 5 条）。
#
#  ★ 与 v8.0（openmv_code/main.py，已归档到 E 盘）的根本区别
#    v8.0 让 OpenMV 直接驱动 L298N 电机并直接开关激光，这已被架构冻结版否决：
#    1) v8.0 的 IN1 与 ENA 同为 P1、IN2 与 ENB 同为 P2 —— 方向与调速互相覆盖；
#    2) v8.0 把 P4 分配给 motor_r2，而 UART(3) 就是 P4/P5 —— 串口输出会串进
#       电机引脚；
#    3) 激光安全时序散落在 OpenMV 一侧，F407 侧无任何闸门。
#    本文件只发 ASCII 行命令，激光与舵机的**物理时序由 F407 计时完成**。
#
# -----------------------------------------------------------------------------
#  协议：严格对齐已编译入库的 F407 侧 Core/Src/openmv_link.c
#  -----------------------------------------------------------------------------
#  上行（OpenMV → F407，USART3：P4 TX → F407 PD9 RX；P5 RX ← PD8 TX）
#    PING            心跳（每 <1.5s 必须发一次，见下方看门狗约束）
#    PS<speed>       pan 速度，-100..100，0=停      例：PS-50
#    TA<deg>         tilt 角度，0..180              例：TA95
#    S3A<deg> S4A<deg> 备用舵机 3/4 角度（未装舵机时 F407 仅回 OK）
#    FIRE<ms>        申请点射，1..2000（F407 有硬上限）
#    L0              主动关激光（进入冷却时立即发）
#    STOP            急停：停 pan + 关激光
#
#    ⚠ 是**粘连式**、不是逗号式。openmv_link.c 用的是 atoi(line+4)，
#      发 "FIRE,300,1" 会让 atoi(",300,1")==0 → F407 判非法 → 回 ERR 且不开火。
#      （《UART协议推进方案》里提到的逗号式 + cls 字段仍是**待办**，尚未实现，
#        因此本固件暂不依赖 cls，改由端侧做类别过滤，见 SAFETY 说明。）
#
#  下行（F407 → OpenMV）
#    READY   F407 上电主动发出
#    OK      上一条命令已合法执行
#    ERR     上一条命令非法（字段/范围不对），未执行
#    PONG    回应 PING
#
#  ⚠ 看门狗硬约束：F407 的 OPENMV_LINK_WATCHDOG_MS = 1500ms，
#    连续 1500ms 没收到**任何合法帧**就强制 pan 停 + 激光关。
#    ⇒ 本固件保证任何状态下都有帧在发，最长间隔 < 1.4s。
#
# =============================================================================

import sensor
import time
import pyb
from pyb import UART, LED

# =============================================================================
# 一、识别参数（LAB 色块法 · 保守门限）
# -----------------------------------------------------------------------------
# 策略来自《UART协议推进方案》第五节：宁可漏打，绝不误伤。
# ⚠ BLOB_THRESH 必须用 OpenMV IDE 的「阈值编辑器」在**固定曝光**下现场标定；
#   下面这组值是从旧文件继承的起点值，不是标定结果。
# =============================================================================
DETECT_MODE = "lesion"          # "lesion"=病斑色块   "weed"=杂草色块
BLOB_THRESH = {
    "lesion": [(20, 90, 10, 70, 5, 55), (10, 70, -10, 30, 30, 80)],
    "weed":   [(30, 100, -20, 20, -20, 20)],
}

PIXELS_MIN = 300
AREA_MIN   = 300

# 目标合理性校验：防止把"整片叶子""大面积阴影"当成目标直接开火
TARGET_AREA_MIN   = 200     # 低于此值视为噪声/杂斑
TARGET_AREA_MAX   = 26000   # 高于此值大概率是整块叶面或阴影
TARGET_AREA_JUMP  = 3.0     # 面积突变超过 3 倍 → 判定换了目标，锁定重置

# =============================================================================
# 二、视觉伺服参数
# =============================================================================
FRAME_W, FRAME_H = 320, 240

DEADZONE_PX   = 15         # 对准死区（像素），与初版 weeder.py 保持一致
LOCK_FRAMES   = 5          # 连续 N 帧落入死区才确认锁定
KP_PAN        = 0.35
PAN_SPEED_MAX = 60
KP_TILT       = 0.15
TILT_DIR      = 1          # 装反了就改成 -1，不要去改 F407 驱动层
TILT_MIN      = 30
TILT_MAX      = 150
TILT_CENTER   = 90

SCAN_SPEED    = 25         # 扫描转速（0..100，符号=方向）
SCAN_TIMEOUT_MS = 60000   # 扫描超时后停转待机

# =============================================================================
# 三、发射安全闸（OpenMV 侧第一道闸；F407 侧目前还没有 cls/冷却闸）
# -----------------------------------------------------------------------------
# 背景：《UART协议推进方案》指出 F407 收到 FIRE<ms> 是**无条件执行**的，
#       所以 OpenMV 侧必须自带全部约束，否则一次误检就是一记激光。
# =============================================================================
LASER_HOLD_MS     = 800    # 单次点射时长（F407 上限 2000）
COOLDOWN_MS       = 2500   # 本机冷却，比 F407 期望的 2000 更严
MAX_SHOTS_TOTAL   = 200    # 本次上电总发射预算，热保护
MAX_SHOTS_PER_MIN = 30     # 每分钟发射上限
MAX_SHOTS_PER_TGT = 3      # 单目标最多连发，打不死就放过，绝不无限循环打同一点

# 端侧类别过滤：识别为作物(crop)时一律按"无目标"处理，不申请开火。
# 这是当前唯一能替代 F407 `cls` 否决的手段（F407 侧该闸尚未实现）。
CLASS_CROP = 0
CLASS_WEED = 1

# =============================================================================
# 四、链路时序
# =============================================================================
UART_ID       = 3          # OpenMV4 H7 上 UART(3) = P4(TX)/P5(RX)，这两个脚只做串口
UART_BAUD     = 115200
HEARTBEAT_MS  = 1000       # 心跳周期，必须 < F407 看门狗 1500ms
FIRE_WAIT_MS  = 400        # 发 FIRE 后等待 FIRE 效果确认的时长（非阻塞，按帧计时）

# =============================================================================
# 五、调试开关
# =============================================================================
# ★ 激光联调总闸：True = FIRE 请求被拦截并替换成 L0，**F407 不会点亮激光**。
#   识别、视觉伺服、状态机全部照常运行，只是不动光。
#   必须先把回环测试跑通、阈值标定完成，才允许改回 False 上真激光。
LASER_DRY_RUN = True

# ★ 曝光标定：首次调试设 True，固件会打印自动收敛到的
#   exposure_us / gain_db，把它们抄到下面两行后改回 False。
EXPOSURE_CALIBRATE = False
EXPOSURE_US = 12000     # 固定曝光（微秒）
GAIN_DB = 4             # 固定增益（dB）

# 调试期关心跳会触发 F407 看门狗，仅用于单步调试，不可量产
DISABLE_HEARTBEAT = False


# =============================================================================
# 六、链路封装
# =============================================================================
# 全局登记唯一的 UART 实例：异常兜底路径必须复用它，
# 绝不能像旧 weeder.py 那样 `GimbalLink().estop()` 新建第二个 UART3。
_ACTIVE_LINK = None


class Link:
    """UART3 ASCII 行协议。整个程序共用**这一个** UART 实例。

    旧版 weeder.py 在异常兜底里写 `GimbalLink().estop()` —— 重新构造了一个
    UART3，在 MicroPython 上很可能初始化失败或破坏已工作的实例，导致急停
    根本发不出去。这里用模块级 _ACTIVE_LINK 登记实例，兜底路径复用同一对象。
    """

    def __init__(self):
        global _ACTIVE_LINK
        self.uart = UART(UART_ID, UART_BAUD, timeout=0)
        _ACTIVE_LINK = self
        self.rx_buf = b""
        self.last_tx = 0            # 最近一次成功发送的时刻
        self.dry = LASER_DRY_RUN
        self.f407_ready = False
        self.err_count = 0
        self.ok_count = 0

    # ---- 发送 ----
    def _raw(self, s):
        if self.dry and s.startswith("FIRE"):
            print("[dry-run] FIRE 被拦截:", s)
            s = "L0"
        try:
            self.uart.write(s + "\n")
            self.last_tx = time.ticks_ms()
        except Exception as e:
            print("[uart] 发送异常:", e)

    def ping(self):     self._raw("PING")
    def pan_speed(self, v):
        self._raw("PS%d" % max(-100, min(100, int(v))))
    def pan_stop(self): self._raw("PS0")
    def tilt(self, deg):
        self._raw("TA%d" % max(0, min(180, int(deg))))
    def laser_off(self): self._raw("L0")
    def estop(self):     self._raw("STOP")

    def fire(self, ms):
        """申请点射。**不等待、不阻塞** —— 计时与物理关断都在 F407 侧。"""
        ms = max(1, min(2000, int(ms)))
        self._raw("FIRE%d" % ms)
        self._raw("PS0")          # 顺便停 pan（同一行窗口内，减少一次循环）

    # ---- 接收（非阻塞）----
    def poll(self):
        """把积压下行字节解成事件，返回 dict。"""
        ev = {"ready": False, "ok": False, "err": False, "pong": False}
        try:
            n = self.uart.any()
            if not n:
                return ev
            self.rx_buf += self.uart.read(min(n, 64))
        except Exception as e:
            print("[uart] 接收异常:", e)
            self.rx_buf = b""
            return ev

        # F407 行缓冲只有 32 字节，异常时最多按 32 字节截断，防内存膨胀
        if len(self.rx_buf) > 128:
            self.rx_buf = self.rx_buf[-64:]

        while b"\n" in self.rx_buf:
            line, self.rx_buf = self.rx_buf.split(b"\n", 1)
            line = line.strip().replace(b"\r", b"")
            if not line:
                continue
            try:
                s = line.decode("ascii", "ignore").strip()
            except Exception:
                continue
            if s == "READY":
                ev["ready"] = True
                self.f407_ready = True
            elif s == "PONG":
                ev["pong"] = True
            elif s == "OK":
                ev["ok"] = True
                self.ok_count += 1
            elif s == "ERR":
                ev["err"] = True
                self.err_count += 1
                print("[link] F407 回 ERR —— 命令非法或越界，检查帧格式")
            else:
                print("[link] 未知下行帧:", s)
        return ev

    def silent_ms(self):
        """距离上次发送的静默时长，用于驱动心跳。"""
        return time.ticks_diff(time.ticks_ms(), self.last_tx)


# =============================================================================
# 七、发射预算
# =============================================================================
class FireGovernor:
    """OpenMV 侧全部开火约束的总闸。can_fire() 为假时一律不开火。"""

    def __init__(self):
        self.total = 0
        self.per_target = 0
        self.minute = 0
        self.minute_mark = time.ticks_ms()

    def _roll(self):
        if time.ticks_diff(time.ticks_ms(), self.minute_mark) >= 60000:
            self.minute_mark = time.ticks_ms()
            self.minute = 0

    def new_target(self):
        self.per_target = 0

    def can_fire(self):
        self._roll()
        if self.total >= MAX_SHOTS_TOTAL:
            return False, "已达总预算 %d，停止作业" % MAX_SHOTS_TOTAL
        if self.minute >= MAX_SHOTS_PER_MIN:
            return False, "已达每分钟上限 %d（热保护）" % MAX_SHOTS_PER_MIN
        if self.per_target >= MAX_SHOTS_PER_TGT:
            return False, "单目标连发已达 %d 次，放弃该目标" % MAX_SHOTS_PER_TGT
        return True, ""

    def note_fire(self):
        self._roll()
        self.total += 1
        self.per_target += 1
        self.minute += 1


# =============================================================================
# 八、检测
# =============================================================================
def classify(area):
    """端侧类别判定。

    真正的 crop/weed 判别需要分类模型；当前固件用面积区间做**保守代理**：
    小而密集的斑点判为疑似杂草(large conf)，大块判为作物/叶面(不打)。
    这个代理很粗糙，所以它只是"第一道过滤"，绝不能当作安全保证 ——
    真正的安全保证必须是 F407 侧的 cls 否决闸（当前尚未实现，见 M1 待办）。
    """
    if area < TARGET_AREA_MIN:
        return CLASS_CROP, 0.0            # 太碎 → 当噪声，不打
    if area > TARGET_AREA_MAX:
        return CLASS_CROP, 0.0            # 太大 → 叶面/阴影，绝不能打
    # 归一化置信度：越接近目标区间上缘越像"成片杂草"
    conf = (float(area) - TARGET_AREA_MIN) / float(max(TARGET_AREA_MAX - TARGET_AREA_MIN, 1))
    if area <= 4000:
        return CLASS_WEED, max(0.35, min(0.9, conf))   # 小片斑点：疑似杂草
    return CLASS_CROP, 0.2               # 偏大：保守当作物


def detect(img):
    """返回 (cx, cy, area, cls, conf)；无目标返回 None。"""
    thresh = BLOB_THRESH.get(DETECT_MODE, BLOB_THRESH["lesion"])
    try:
        blobs = img.find_blobs(thresh,
                               pixels_threshold=PIXELS_MIN,
                               area_threshold=AREA_MIN,
                               merge=True)
    except Exception as e:
        print("[detect] 异常:", e)
        return None
    if not blobs:
        return None
    b = max(blobs, key=lambda x: x.area())
    area = b.area()
    cls, conf = classify(area)
    return b.cx(), b.cy(), area, cls, conf


# =============================================================================
# 九、主流程
# =============================================================================
S_INIT, S_SCAN, S_AIM, S_FIRE_WAIT, S_COOLDOWN, S_IDLE, S_FAULT = range(7)
STATE_CN = {
    S_INIT: "握手", S_SCAN: "扫描", S_AIM: "瞄准", S_FIRE_WAIT: "点火等待",
    S_COOLDOWN: "冷却", S_IDLE: "待机", S_FAULT: "故障",
}


def safe_shutdown(link, reason):
    """任何退出路径都必须经过这里：急停 + 关激光。"""
    print("[safe] " + reason)
    try:
        link.estop()        # STOP：F407 侧停 pan + 关激光
        link.laser_off()    # L0：冗余再关一次
    except Exception as e:
        print("[safe] 急停发送失败:", e)


def run():
    # ---------------- 摄像头 ----------------
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)

    # ⚠ 用显式循环预热，不用 sensor.skip_frames(2000)。
    #   旧 weeder.py 写的是 skip_frames(2000)，在不同 OpenMV 固件里该位置参数
    #   会被解释成"跳过 2000 帧"，导致上电后长时间黑屏、像是没反应。

    if EXPOSURE_CALIBRATE:
        # ---- 标定模式：先让自动曝光收敛，再把测得值锁死 ----
        # 只关 auto_exposure 是**不够**的：不带参数调用会把增益锁在
        # reset() 后的默认值上，通常偏暗，画面和识别都不工作。
        # 这里先跑 1.5s 自动收敛，读回实际值打印出来，
        # 把它抄进下面的 EXPOSURE_US / GAIN_DB 即可长期固定。
        sensor.set_auto_gain(True)
        sensor.set_auto_whitebal(True)
        sensor.set_auto_exposure(True)
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 1500:
            sensor.snapshot()
        auto_us = sensor.get_exposure_us()
        auto_db = sensor.get_gain_db()
        print("[calib] 自动收敛结果: exposure_us=%d gain_db=%d" % (auto_us, auto_db))
        print("[calib] 请把这两个值填入 EXPOSURE_US / GAIN_DB，"
              "然后把 EXPOSURE_CALIBRATE 改回 False")
    else:
        sensor.set_auto_gain(False)
        sensor.set_auto_whitebal(False)
        sensor.set_auto_exposure(False)
        # ★ 显式给值。缺这两行会导致画面严重偏暗（直方图全挤在暗部），
        #   色块 LAB 阈值随之全部失效。
        sensor.set_gain_db(GAIN_DB)
        sensor.set_exposure_us(EXPOSURE_US)

    for _ in range(20):
        sensor.snapshot()
    print("[boot] 分辨率 %dx%d  曝光 %dus  增益 %ddB（均已锁定）" % (
        sensor.width(), sensor.height(),
        sensor.get_exposure_us(), sensor.get_gain_db()))

    led = LED(1)
    link = Link()
    gov = FireGovernor()

    # ---------------- INIT：等 F407 上电 ----------------
    # F407 在 OpenmvLink_Init() 里主动发 "READY"；这里循环请求 PING 以兜底。
    state = S_INIT
    t0 = time.ticks_ms()
    t_ping = 0
    print("[boot] 等待 F407 应答...")
    while state == S_INIT:
        ev = link.poll()
        if ev["ready"] or ev["pong"] or ev["ok"]:
            print("[boot] F407 链路就绪")
            state = S_SCAN
            break
        # 每 400ms 探一次，不阻塞
        if time.ticks_diff(time.ticks_ms(), t_ping) > 400:
            link.ping()
            t_ping = time.ticks_ms()
        sensor.snapshot()          # 空转取帧维持 IDE 画面，不做识别
        if time.ticks_diff(time.ticks_ms(), t0) > 10000:
            # F407 没来：仍然继续发命令（它可能后上电），
            # 但状态机停在 IDLE 等，避免无人应答时乱转云台。
            print("[boot] 10s 未等到 F407，进入待机（继续后台发心跳）")
            state = S_IDLE
            break

    # ---------------- 主状态机 ----------------
    link.pan_stop()
    link.tilt(TILT_CENTER)
    link.laser_off()

    tilt_a = TILT_CENTER
    lock_count = 0
    t_state = time.ticks_ms()
    t_scan = time.ticks_ms()
    tgt_area = 0
    tgt_cls = CLASS_CROP
    frames = 0
    fps_mark = time.ticks_ms()
    fps = 0
    status_ticks = 0
    frame_interval = 80     # 目标 ~12fps；不设太高，给 IDE 留 USB 带宽

    while True:
        link.poll()          # 持续排空下行，避免 F407 的 32 字节缓冲被写满丢帧
        img = sensor.snapshot()

        # ---- 心跳：保证任何状态下距上次发送 < 1500ms，喂饱 F407 看门狗 ----
        if not DISABLE_HEARTBEAT and link.silent_ms() > HEARTBEAT_MS:
            link.ping()

        now = time.ticks_ms()
        el_state = time.ticks_diff(now, t_state)

        # ================= SCAN：匀速扫描 =================
        if state == S_SCAN:
            link.pan_speed(SCAN_SPEED)
            d = detect(img)
            if d:
                cx, cy, area, cls, conf = d
                # 端侧过滤：判为作物就不当作目标，继续扫
                if cls == CLASS_CROP:
                    pass
                elif tgt_area and area / float(max(tgt_area, 1)) > TARGET_AREA_JUMP:
                    # 面积突变 → 换了目标，锁定计数作废重来
                    lock_count = 0
                else:
                    tgt_area, tgt_cls = area, cls
                    link.pan_stop()
                    lock_count = 0
                    gov.new_target()
                    print("[scan] 发现目标 area=%d cls=%d，转瞄准" % (area, cls))
                    state = S_AIM
                    t_state = now
            elif time.ticks_diff(now, t_scan) > SCAN_TIMEOUT_MS:
                link.pan_stop()
                print("[scan] 扫描超时，停转待机")
                state = S_IDLE
                t_state = now

        # ================= AIM：视觉伺服趋近 =================
        elif state == S_AIM:
            d = detect(img)
            if not d or d[3] == CLASS_CROP:
                # 目标丢失：低速保持当前方向继续找
                lock_count = 0
                tgt_area = 0
                link.pan_speed(SCAN_SPEED // 2)
                state = S_SCAN
                t_scan = now
                print("[aim] 目标丢失，回扫描")
            else:
                cx, cy, area, cls, conf = d
                tgt_area = area

                err_x = cx - FRAME_W // 2
                err_y = cy - FRAME_H // 2

                # pan：像素误差 → 速度
                if abs(err_x) < DEADZONE_PX:
                    link.pan_stop()
                else:
                    v = KP_PAN * err_x
                    link.pan_speed(max(-PAN_SPEED_MAX, min(PAN_SPEED_MAX, v)))

                # tilt：像素误差 → 角度增量
                if abs(err_y) >= DEADZONE_PX:
                    tilt_a += TILT_DIR * KP_TILT * err_y
                    tilt_a = max(TILT_MIN, min(TILT_MAX, tilt_a))
                    link.tilt(tilt_a)

                if abs(err_x) < DEADZONE_PX and abs(err_y) < DEADZONE_PX:
                    lock_count += 1
                    if lock_count >= LOCK_FRAMES:
                        ok, why = gov.can_fire()
                        if not ok:
                            print("[aim] 熔断：%s" % why)
                            state = S_FAULT
                            t_state = now
                            tgt_area = 0
                        else:
                            gov.note_fire()
                            link.fire(LASER_HOLD_MS)      # 非阻塞：F407 侧计时
                            print("[fire] 申请点射 %dms（第 %d 次，单目标 %d）"
                                  % (LASER_HOLD_MS, gov.total, gov.per_target))
                            state = S_FIRE_WAIT
                            t_state = now
                            lock_count = 0
                else:
                    lock_count = 0

        # ================= FIRE_WAIT：等激光打完（按帧计时，不阻塞）=====================
        elif state == S_FIRE_WAIT:
            link.pan_stop()
            if el_state >= FIRE_WAIT_MS:
                link.laser_off()          # L0 冗余，确保关闭（双保险）
                state = S_COOLDOWN
                t_state = time.ticks_ms()
                t_scan = time.ticks_ms()
                print("[fire] 冷却 %.1fs" % (COOLDOWN_MS / 1000.0))
                if gov.per_target >= MAX_SHOTS_PER_TGT:
                    print("[fire] 单目标熔断，跳过该点继续扫描")
                    tgt_area = 0

        # ================= COOLDOWN =================
        elif state == S_COOLDOWN:
            link.pan_stop()
            link.laser_off()
            if el_state >= COOLDOWN_MS:
                tgt_area = 0
                state = S_SCAN
                t_state = time.ticks_ms()
                t_scan = time.ticks_ms()

        # ================= IDLE：停转待机，但保持心跳 =================
        elif state == S_IDLE:
            link.pan_stop()
            # 若 F407 此时上线，自动恢复扫描
            ev = link.poll()
            if ev["ready"] or ev["pong"]:
                print("[idle] F407 已应答，恢复扫描")
                state = S_SCAN
                t_state = time.ticks_ms()
                t_scan = time.ticks_ms()

        # ================= FAULT：熔断后停机待命，保持心跳 =================
        elif state == S_FAULT:
            link.pan_stop()
            link.laser_off()
            if el_state > 30000:      # 30s 后允许人工取景重试
                gov = FireGovernor()
                tgt_area = 0
                lock_count = 0
                state = S_SCAN
                t_state = time.ticks_ms()
                t_scan = time.ticks_ms()
                print("[fault] 预算已重置，恢复扫描")

        # ---- 帧率统计与低频状态行（联调要看的东西）----
        frames += 1
        d_ms = time.ticks_diff(time.ticks_ms(), fps_mark)
        if d_ms >= 1000:
            fps = int(frames * 1000.0 / d_ms)
            frames = 0
            fps_mark = time.ticks_ms()
            status_ticks += 1
            if status_ticks % 5 == 0:
                print("[stat] fps=%d state=%s tgt=%d area=%d shots=%d/%d/%d ok=%d err=%d"
                      % (fps, STATE_CN.get(state, "?"), lock_count, tgt_area,
                         gov.per_target, gov.minute, gov.total,
                         link.ok_count, link.err_count))

        led.on()
        time.sleep_ms(frame_interval)
        led.off()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[exit] 用户中断")
    except Exception as e:
        print("\n[exit] 致命异常:", e)
        try:
            import sys
            sys.print_exception(e)
        except Exception:
            pass
    finally:
        # 无论怎么退出都要急停。复用 run() 里已经建好的那个 UART 实例，
        # 只有在 run() 还没走到建链这一步时才新建。
        try:
            if _ACTIVE_LINK is None:
                _ACTIVE_LINK = Link()
            safe_shutdown(_ACTIVE_LINK, "退出前强制急停")
        except Exception:
            pass
