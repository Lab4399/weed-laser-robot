# OpenMV 端固件说明（两代架构，协议不通用）

这个目录下有两套**互不兼容**的 OpenMV 固件。选错的那套，接线再对也通不了 ——
而且失败方式很隐蔽：串口有波形、F407 也不报错，只是 `vp_frames_ok` 永远是 0。

---

## 一眼选型

| 目录 / 文件 | 协议 | 配套的 F407 固件 | 状态 |
|---|---|---|---|
| `weeder.py` / `main.py` / `main_diag.py` | **V1.1 粘连式**：`PING` `PS<speed>` `TA<deg>` `FIRE<ms>` `STOP` | GoodDog（交付包 9-28 那版，USART3 PD8/PD9） | 旧架构，**当前未使用** |
| `vision_node/` | **`@T,seq,class,conf,cx,cy,w,h,dist*crc`** 帧 | `firmware/stm32f407/` 应用层固件（USART1 PA9/PA10） | **当前烧的就是这套** |

> 2026-10-19 把 F407 换成了新应用层固件（见 `docs/F407固件构建与烧录.md`），
> 因此 OpenMV 也必须换成 `vision_node/`。仓库根 `openmv/weeder.py` 那套
> 对应的是更早的 GoodDog 固件，两者不能混用。

---

## 两套协议差在哪

**V1.1（旧）** —— 人读友好，双向命令：

```
OpenMV → F407 : PING / PS50 / TA90 / FIRE300 / L0 / STOP
F407 → OpenMV : READY / OK / ERR / PONG
```

**`@T` 帧（新）** —— 定长字段 + CRC-8，单向遥测：

```
@T,104,WEED,0.88,52,131,60,71,0*6C\n
   │   │    │    │  │   │  │  │  └ 距离 mm
   │   │    │    │  │   │  │  └── 高
   │   │    │    │  │   │  └───── 宽
   │   │    │    │  │   └──────── 中心 Y
   │   │    │    │  └──────────── 中心 X
   │   │    │    └─────────────── 置信度
   │   │    └──────────────────── 类别 WEED / CROP / NONE
   │   └───────────────────────── 序号
   └───────────────────────────── 帧头
```

CRC-8（poly 0x07，初值 0），覆盖 `*` 之前的全部字节，以两位大写十六进制附在末尾。

---

## 当前 J 盘上部署的是哪套

`vision_node/` 全部 7 个文件已复制到 OpenMV 的 U 盘根目录（`/flash`）。
其中两处**为首次联调改过**，改回前请先看注释：

| 项 | 值 | 原因 |
|---|---|---|
| `config.DETECTOR` | `"blob"` | 还没有配套的 FOMO 检测模型；仓库里的 `*_int8.tflite` 是**分类**模型，不是检测模型 |
| `config.GIMBAL_ENABLE` | `False` | F407 的 TIM3 也在输出舵机 PWM，接线未核实前不能让两个主控争同一路 |

---

## 烧到 OpenMV 上

```bash
cp openmv/vision_node/*.py /j/
```

> ⚠️ OpenMV 写完文件**不会自动重启**：J 盘持续挂载、固件根本不执行、COM4 全程静默。
> 必须物理拔插一次 USB，或者用 IDE 点「运行」。
>
> 也可以不拔插，直接从 REPL 拉起来（实测可用）：
> ```python
> import sys; sys.path.insert(0, '/flash')
> exec(open('/flash/main.py').read())
> ```
