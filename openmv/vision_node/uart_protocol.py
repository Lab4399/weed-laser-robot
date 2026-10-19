# -*- coding: utf-8 -*-
# ============================================================================
#  协议 v1.1 帧组装 + CRC-8
#
#  帧格式：
#      @T,SEQ,CLASS,CONF,CX,CY,W,H,DIST*HH\n
#
#  示例（校验值已用本文件实现实算，可直接用于两边比对）：
#      @T,0,NONE,0.00,0,0,0,0,0*56
#      @T,104,WEED,0.88,52,131,60,71,0*6C      ← 目标偏左
#      @T,105,WEED,0.77,288,126,48,55,0*B6     ← 目标偏右
#      @T,103,NONE,0.00,0,0,0,0,0*D3
#
#  算法校验：crc8(b"123456789") == 0xF4（CRC-8/ATM 标准校验值）。
#  若你的实现算不出 0xF4，说明多字节增量写法有误，不要继续往下联调 ——
#  现象会表现为"每一帧都判 CRC 错"，而抓包看帧本身完全正常，极难反推。
#
#  v1.1 相对 v1.0 的两处改动（都是必需的，不是优化）：
#    1. 末尾加 *HH 校验（CRC-8, poly=0x07, init=0x00）
#       原 ASCII 帧无校验，一个被噪声翻转的字节就能让 CX=173 变成 773，
#       F407 会据此大幅打舵。这条链最终驱动电机，必须有校验。
#    2. 新增 DIST 字段（毫米，0 表示无效）
#       项目核心路线是双目测距，协议不预留则后续加字段要全链路重改。
#
#  为什么保留 ASCII 而不是换二进制：
#     调试阶段可以直接用串口助手看原始帧、用逻辑分析仪逐字节比对。
#     带宽完全不是瓶颈（一帧约 40 字节，50ms 一帧 => 800 B/s，115200 够用 140 倍）。
#     等系统稳定后若要换二进制，必须同时升版本号并让 F407 双协议兼容。
# ============================================================================

import config

# CRC-8 查表（poly 0x07）。表在导入时生成，避免每次循环重算。
_CRC8_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c << 1) ^ 0x07) & 0xFF if (_c & 0x80) else (_c << 1) & 0xFF
    _CRC8_TABLE.append(_c)


def crc8(data):
    """data: bytes 或 bytearray。返回 0..255。"""
    crc = 0
    for b in data:
        crc = _CRC8_TABLE[crc ^ b]
    return crc


class FrameBuilder:
    """组装并发送视觉帧。维护自增 SEQ，供 F407 检测丢帧。"""

    # 类别编码必须与 F407 的 vision_proto.h 中 class 枚举严格一致
    CLS_NONE = "NONE"
    CLS_WEED = "WEED"
    CLS_CROP = "CROP"

    def __init__(self, uart):
        self._uart = uart
        self._seq = 0
        self._sent = 0
        self._crc_fail = 0   # 本节点不校验接收，保留计数位给后续双向协议

    def next_seq(self):
        s = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        return s

    def send_target(self, cls, conf, cx, cy, w, h, dist_mm):
        """
        发送一帧目标数据。
        cls      : CLS_NONE / CLS_WEED / CLS_CROP
        conf     : 0.0 ~ 1.0
        cx, cy   : 目标中心像素坐标
        w, h     : 目标框宽高（像素）
        dist_mm  : 距离毫米，0 表示无效/未标定
        """
        seq = self.next_seq()

        # 字段范围收口后再发送。宁可发 NONE，也不发一个越界值，
        # 因为 F407 侧对越界帧的处理是"整帧丢弃"，不如主动降级为 NONE。
        if cls == self.CLS_NONE or conf < config.CONF_MIN_SEND:
            body = "@T,%d,%s,0.00,0,0,0,0,0" % (seq, self.CLS_NONE)
        else:
            cx = max(0, min(32767, int(cx)))
            cy = max(0, min(32767, int(cy)))
            w = max(0, min(32767, int(w)))
            h = max(0, min(32767, int(h)))
            dist = max(0, min(65535, int(dist_mm)))
            body = "@T,%d,%s,%.2f,%d,%d,%d,%d,%d" % (
                seq, cls, conf, cx, cy, w, h, dist)

        raw = body.encode()
        frame = raw + b"*%02X\n" % crc8(raw)

        self._uart.write(frame)
        self._sent += 1
        return frame

    def stats(self):
        return (self._seq, self._sent, self._crc_fail)

    # ---- 供上位机调试用：本地自检 ----
    @staticmethod
    def selftest():
        """
        在 REPL 里执行 uart_protocol.FrameBuilder.selftest() 验证实现正确。
        全部输出 OK 才说明本节点与 F407 侧的 CRC 一致。
        """
        vectors = [
            (b"123456789", 0xF4),                      # CRC-8/ATM 标准校验值
            (b"@T,0,NONE,0.00,0,0,0,0,0", 0x56),
            (b"@T,104,WEED,0.88,52,131,60,71,0", 0x6C),
            (b"@T,105,WEED,0.77,288,126,48,55,0", 0xB6),
            (b"@T,103,NONE,0.00,0,0,0,0,0", 0xD3),
        ]
        all_ok = True
        for raw, expect in vectors:
            got = crc8(raw)
            ok = (got == expect)
            all_ok = all_ok and ok
            print("%s crc=%02X expect=%02X  %s" % (
                "OK  " if ok else "FAIL", got, expect, raw.decode()))
        print("selftest:", "PASS" if all_ok else "FAIL")
        return all_ok
