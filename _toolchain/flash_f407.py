# -*- coding: utf-8 -*-
r"""
flash_f407.py —— STM32F407 固件烧录工具

当前状态：⚠️ 需要先装 ST-Link 驱动 + 烧录软件才能用
========================================================================

诊断结论（2026-10-19 实测）
------------------------------------------------------------------------
ST-Link 硬件已被系统识别：
    VID=0483 PID=3748  =  STMicroelectronics ST-Link V2
但驱动状态为：
    Status   = Error
    Problem  = CM_PROB_FAILED_INSTALL      <-- 根因
    ProblemDescription = 无法安装设备驱动程序

后果：任何烧录软件都连不上 ST-Link，因为底层 USB 驱动没装上。
这不是固件问题，也不是接线问题，是**驱动没装**。

另外本机当前没有任何烧录工具：
    STM32CubeProgrammer / ST-LINK_CLI / OpenOCD / JLink  全部未安装

------------------------------------------------------------------------
烧录前必须完成两步（都需要你手动操作）
------------------------------------------------------------------------

【第 1 步】装 ST-Link 驱动
    下载 STSW-LINK009（ST-Link/V2 驱动）并安装：
    https://www.st.com/en/development-tools/stsw-link009.html
    或下整个 STM32CubeProgrammer（自带驱动），见第 2 步

    ⚠️ 装驱动时如果 Windows 弹出「Windows 安全中心」警告，
       选「仍然安装」。ST 驱动有时被误判。

【第 2 步】装 STM32CubeProgrammer
    https://www.st.com/en/development-tools/stm32cubeprog.html
    下载后默认装到：
        C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\

装完回来告诉我，我用 --check 自检，确认驱动和工具都就位再实际烧录。

------------------------------------------------------------------------
用法
------------------------------------------------------------------------
    python _toolchain\flash_f407.py --check              # 只做环境自检（安全）
    python _toolchain\flash_f407.py --info# 读取芯片信息，不写入
    python _toolchain\flash_f407.py --flashverify # 烧录+校验
    python _toolchain\flash_f407.py --backup               # 先备份芯片现有固件

⚠️ 烧录是**破坏性操作**，会覆盖芯片 Flash 里的现有固件。
   执行前务必用 --backup 备份，尤其是这块 F407 上可能还有
   交付包之外的现场调试代码。

关于固件镜像的选择
------------------------------------------------------------------------
交付包 02_单片机固件/小车_完整备份/ 下的镜像**不要随便烧**：

  f407_current_20260928_含GoodDog.bin   1 MB  含 GoodDog 的当前固件全片镜像
  f407_firmware_35KB.bin                35 KB  仅前 35KB，看起来像应用区段
  f407_firmware.hex                    98 KB  Intel HEX，地址信息明确
  f407_flash_1MB.bin1 MB  整片 Flash dump（含 bootloader + 空白区）

  ⚠️ f407_flash_1MB.bin 是**读出来的 dump**，通常不需要烧回去。
  ⚠️ 各镜像是否等价、哪个是"当前正在跑的"，交付包里没有明确说明，
     **必须先 --backup 备份现有芯片，再由实验室同学确认烧哪个。**
     我不替你判断这个选择 —— 烧错固件会让小车直接不能动。
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

# 交付包固件镜像目录
BAK = r"C:\Users\Administrator\WorkBuddy\2026-10-11-21-21-58\work\实验室交付包_纯净版\02_单片机固件\小车_完整备份"

# 可能的 STM32CubeProgrammer 安装路径
CANDIDATE_CLI = [
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
    r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
    r"C:\ST\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.stlink-gdb-server.win32_*\tools\bin\ST-LINK_CLI.exe",
    r"C:\Program Files (x86)\GNU Arm Embedded Toolchain",
]


def hr(t):
    print("\n" + "=" * 68)
    print(f"  {t}")
    print("=" * 68)


def find_cli():
    """定位 STM32_Programmer_CLI.exe"""
    for p in CANDIDATE_CLI:
        if os.path.isfile(p):
            return p
        # 处理通配符路径
        if '*' in p:
            m = glob.glob(p)
            if m:
                return m[0]
    # 全盘兜底搜一次
    for root in (r"C:\Program Files\STMicroelectronics",
                 r"C:\Program Files (x86)\STMicroelectronics"):
        if os.path.isdir(root):
            hit = glob.glob(os.path.join(root, "**", "STM32_Programmer_CLI.exe"),
                            recursive=True)
            if hit:
                return hit[0]
    return None


def check_driver():
    """检查 ST-Link 驱动状态"""
    hr("第 1 层：ST-Link 驱动状态")
    try:
        ps = (
            "Get-CimInstance Win32_PnPEntity | "
            "Where-Object { $_.DeviceID -like 'USB\\VID_0483*' } | "
            "ForEach-Object { \"$($_.Name)|$($_.Status)|$($_.ConfigManagerErrorCode)\" }"
        )
        out = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception as e:
        print(f"  查询失败：{e}")
        return False

    lines = [x for x in out.splitlines() if x.strip()]
    if not lines:
        print("  ❌ 完全没检测到 ST-Link（VID=0483）")
        print("     → 换USB 线试试（有些线只供电不通信），或换 USB 口")
        return False

    ok = False
    for L in lines:
        parts = L.split('|')
        name = parts[0] if parts else '?'
        status = parts[1] if len(parts) > 1 else '?'
        err = parts[2] if len(parts) > 2 else '?'
        # Status 正常时是 'OK'，失败时带 CM_PROB_ 前缀
        good = status.strip() == 'OK' or status.strip() == '0'
        print(f"  {'✅' if good else '❌'} {name}")
        print(f"     Status={status}  ErrorCode={err}")
        if good:
            ok = True
        else:
            print()
            print("     🔧 根因：驱动未安装（CM_PROB_FAILED_INSTALL）")
            print("        ST-Link 硬件已被识别（VID=0483 PID=3748 = ST-Link V2），")
            print("        但 Windows 装不上驱动 —— 这就是烧录连不上的原因。")
            print()
            print("     处理：")
            print("       1) 装 STSW-LINK009 驱动")
            print("          https://www.st.com/en/development-tools/stsw-link009.html")
            print("       2) 或直接装 STM32CubeProgrammer（自带驱动，推荐）")
            print("          https://www.st.com/en/development-tools/stm32cubeprog.html")
            print("       3) 装的时候如果 Windows 拦你，选「仍然安装」")
    return ok


def check_tool():
    hr("第 2 层：烧录工具")
    cli = find_cli()
    if not cli:
        print("  ❌ 没找到 STM32_Programmer_CLI.exe")
        print()
        print("  处理：装 STM32CubeProgrammer（免费，ST 官方）")
        print("     https://www.st.com/en/development-tools/stm32cubeprog.html")
        print()
        print("  默认安装路径：")
        print(r"     C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin")
        return None

    print(f"  ✅ 找到：{cli}")
    ver = subprocess.run([cli, '--version'], capture_output=True, text=True,
                         timeout=60)
    for L in (ver.stdout or '').splitlines():
        if 'STM32CubeProgrammer' in L or 'Version' in L:
            print(f"     {L.strip()}")
    return cli


def list_images():
    hr("交付包里的固件镜像（烧录前请确认烧哪个）")
    d = os.path.join(BAK, '01_F盘小车备份原包', '3备份F407', '01_芯片固件镜像')
    if not os.path.isdir(d):
        print(f"  目录不存在：{d}")
        return
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if os.path.isfile(p):
            print(f"  {os.path.getsize(p):>9,} B   {f}")
    print()
    print("  ⚠️ 这些镜像用途不同，交付包里没写清楚哪个是'当前在跑的'。")
    print("     f407_flash_1MB.bin 是从芯片读出的 dump，通常不需要烧回去。")
    print("     烧错固件小车会直接不能动 —— 请让实验室同学确认后再执行 --flash。")


def run(cli, args, timeout=180):
    print(f"\n$ STM32_Programmer_CLI {' '.join(args)}")
    p = subprocess.run([cli] + args, capture_output=True, text=True,
                       timeout=timeout)
    out = (p.stdout or '') + (p.stderr or '')
    for L in out.splitlines():
        s = L.strip()
        if s and not s.startswith('='):
            print(f"  {s}")
    return p.returncode, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='环境自检（安全）')
    ap.add_argument('--list', action='store_true', help='列出固件镜像')
    ap.add_argument('--info', action='store_true', help='读取芯片信息')
    ap.add_argument('--backup', action='store_true', help='备份芯片现有固件')
    ap.add_argument('--flash', metavar='FILE', help='烧录指定镜像')
    ap.add_argument('--connect', metavar='UNDERLAY', nargs='?', const='SWD',
                    help='指定协议，默认 SWD；也可填 UNDERLAY（老版调试器）')
    ap.add_argument('--freq', type=int, default=4000, help='SWD 频率 kHz')
    a = ap.parse_args()

    print("STM32F407 固件烧录工具")
    print("目标芯片：STM32F407ZGT6（GoodDog 主控）")

    # 默认就是自检
    if a.list:
        list_images()
        return

    drv_ok = check_driver()
    cli = check_tool()
    list_images()

    hr("体检结论")
    if not drv_ok:
        print("  ❌ ST-Link 驱动未安装 —— 现在无法烧录")
        print("     先装驱动（见上方链接），装完重跑 --check")
    if not cli:
        print("  ❌ 缺少烧录工具 —— 现在无法烧录")
    if drv_ok and cli:
        print("  ✅ 驱动与工具均已就绪，可以执行 --info / --backup / --flash")
        print()
        print("  建议顺序：")
        print("     1) --info      先确认能连上芯片，读出 Flash/ID 信息")
        print("     2) --backup    备份现有固件（烧录是破坏性的）")
        print("     3) --flash     烧录（需你指定镜像路径）")

    if a.info and cli and drv_ok:
        hr("读取芯片信息")
        c = a.connect or 'SWD'
        run(cli, ['-c', f'port={c}', f'freq={a.freq}', '-r32', '0xE000ED00', '1',
                  'vp'])      # SCB->CPUID 寄存器
        run(cli, ['-c', f'port={c}', f'freq={a.freq}', '-r32', '0x1FFF7A22', '1',
                  'vp'], timeout=300)   # Flash size寄存器

    if a.backup and cli and drv_ok:
        hr("备份芯片现有固件")
        ts = time.strftime('%Y%m%d_%H%M%S')
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           f'..', 'models', f'f407_backup_{ts}.bin')
        out = os.path.abspath(out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        rc, _ = run(cli, ['-c', f'port={a.connect or "SWD"}',
                          f'freq={a.freq}', '-r', '0x08000000', '0x100000',
                          out, '-v'], timeout=600)
        if rc == 0 and os.path.isfile(out):
            print(f"\n  ✅ 备份完成：{out}")
            print(f"     {os.path.getsize(out):,} 字节")
        else:
            print("\n  ❌ 备份失败 —— **不要烧录**，会丢失现场固件")

    if a.flash:
        hr("烧录")
        print("⚠️  破坏性操作：将覆盖芯片 Flash 现有内容")
        print(f"    镜像：{a.flash}")
        if not os.path.isfile(a.flash):
            print(f"\n  ❌ 文件不存在：{a.flash}")
            return
        print(f"    大小：{os.path.getsize(a.flash):,} 字节")
        print()
        ans = input("确认烧录？输入 yes 继续：")
        if ans.strip().lower() != 'yes':
            print("已取消")
            return
        if cli and drv_ok:
            ext = '.hex' if a.flash.lower().endswith('.hex') else '.bin'
            run(cli, ['-c', f'port={a.connect or "SWD"}',
                      f'freq={a.freq}', '-w', a.flash, '-v', '-rst'],
                timeout=600)


if __name__ == '__main__':
    main()