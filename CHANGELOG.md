# 更新日志

本项目的版本记录。版本号规则见 `docs/版本管理与备份流程.md`。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [v0.1.0] - 2026-10-26

首个版本化基线。此前项目已有 14 次提交（2026-10-15 ~ 10-19），但从未打过标签，
且 10-22/10-23 的成果全部游离在仓库之外。本版把它们收拢进版本控制。

### 新增

- **F407 固件应用层源码入库**：`_f407build/fw/app/`（25 文件，182 KB）
  - `Core/` app_main.c 启动序列、app_tasks.c 4 个 FreeRTOS 任务、app_config.h 全部参数
  - `control/motion.c` 差速控制
  - `drivers/motor.c` 电机、`servo.c` 舵机、`uart_link.c` DMA 串口
  - `protocol/vision_proto.c` `@T` 帧 + CRC-8 状态机
  - `services/safety.c` 安全闸、`param.c` 双 bank Flash 持久化
  - `tests/host_proto_test.c` 与 HAL/FreeRTOS 桩（可在 PC 编译）
- **四份联调文档**：10-状态快照-20261022、11-F407连接失败诊断、12-F407固件结构分析、13-实物接线清单
- **待办总清单**：8 阶段 23 条目，含 9 处风险标记
- **5 个诊断脚本**：openmv_probe2 / openmv_snapshot_probe / read_f407_counters / scan_f407_full / stm32prog.bat
- **`tools/backup.ps1`**：一键备份（预检 → 提交 → 打标签 → 双远端推送）
- **`docs/版本管理与备份流程.md`**：分支、提交、版本号、回滚、多副本收敛的完整规范

### 修复

- **L298N 安全漏洞**（2026-10-23）：`motor_enable(false)` 原实现只拉低 STBY，
  而 L298N 没有 STBY 引脚（PB11 悬空），导致 safety 判定故障后电机仍按上次 PWM 继续转，
  直到 IWDG 复位或人工断电。改为无论使能与否都先清零 PWM 与方向脚。
  *该修复此前一直存在于被 `.gitignore` 排除的目录中，本版首次纳入版本控制。*

### 变更

- `.gitignore`：`_f407build/` 从整目录忽略改为精确放行 `fw/app/`，
  第三方 HAL、CubeMX 生成物、编译产物继续忽略。

### 已知状态

| 项 | 状态 |
| --- | --- |
| OpenMV 侧 | `vision_node` 7 模块，`DETECTOR="blob"`，无 FOMO 模型 |
| F407 侧 | 实机跑通，脱机连续运行 61 秒无复位；固件已读回备份 1 MB |
| 协议 | `@T,SEQ,CLASS,CONF,CX,CY,W,H,DIST*HH` + CRC-8，两端已对拍验证 |
| 工具链 | STM32CubeProgrammer 2.23.0 + CubeIDE 2.1.1 + GCC 14.3.1 可用 |
| **阻塞项** | **缺 FOMO `.tflite` 检测模型**（待办 0.3） |
| 未验证 | 激光控制代码缺失、编码器未接、舵机物理归属待确认 |

---

## 历史（标签建立之前）

| 日期 | 提交 | 内容 |
| --- | --- | --- |
| 2026-10-19 | 1b47fb1 | OpenMV 换成与固件配套的 vision_node，验证 F407 接收链路 |
| 2026-10-19 | 14d8048 | F407 实机跑通：修掉 6 个致命缺陷，脱机连续运行 61 秒无复位 |
| 2026-10-19 | 4a0d103 | 本地调试链路：诊断固件 + PC 监听器 |
| 2026-10-19 | cc8c731 | 核查 OpenMV 芯片状态（J 盘），备份现有固件 |
| 2026-10-19 | f31de3b | 新增烧录工具与指南，定位烧录阻塞根因 |
| 2026-10-16 | f3fb2c0 | 记录交叉验证的两层统计陷阱 |
| 2026-10-16 | d234d69 | 交叉验证性能优化 51 分钟 → 22 秒 |
| 2026-10-15 | 2724fd8 | 除草小车视觉识别：YOLOv8n crop/weed 检测 + 激光执行链 |
