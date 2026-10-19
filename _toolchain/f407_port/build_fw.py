# -*- coding: utf-8 -*-
"""
build_fw.py —— 除草小车 F407 固件构建脚本

替代 Makefile（本机没有 make）。用法：
    python build_fw.py          # 全量构建
    python build_fw.py --clean  # 清理后构建

产物：
    build/fw407.elf / fw407.bin / fw407.map
"""
import os
import subprocess
import sys
import argparse

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fw')
CUBE = os.path.join(HERE, '..', 'cube_f4')
HAL = os.path.join(CUBE, 'Drivers', 'STM32F4xx_HAL_Driver')
CMSISD = os.path.join(CUBE, 'Drivers', 'CMSIS', 'Device', 'ST', 'STM32F4xx')
CMSIS = os.path.join(CUBE, 'Drivers', 'CMSIS')
FRT = os.path.join(CUBE, 'Middlewares', 'Third_Party', 'FreeRTOS', 'Source')
BUILD = os.path.join(HERE, 'build')

TC = os.path.join(
    'E:', os.sep, 'STM32', 'STM32CubeIDE_2.1.1', 'STM32CubeIDE', 'plugins',
    'com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.14.3.rel1.win32_1.0.100.202602081740',
    'tools', 'bin')
CC = os.path.join(TC, 'arm-none-eabi-gcc.exe')
CP = os.path.join(TC, 'arm-none-eabi-objcopy.exe')
SZ = os.path.join(TC, 'arm-none-eabi-size.exe')

CPU = ['-mcpu=cortex-m4', '-mthumb', '-mfpu=fpv4-sp-d16', '-mfloat-abi=hard']
DEFS = ['-DUSE_HAL_DRIVER', '-DSTM32F407xx']
CFLAGS = CPU + DEFS + [
    '-O2', '-g3', '-std=c11', '-Wall', '-Wextra', '-Wshadow',
    '-ffunction-sections', '-fdata-sections', '-fno-common',
]
INCLUDES = [
    HERE,
    os.path.join(HERE, 'app', 'Core'),
    os.path.join(HERE, 'app', 'protocol'),
    os.path.join(HERE, 'app', 'drivers'),
    os.path.join(HERE, 'app', 'control'),
    os.path.join(HERE, 'app', 'services'),
    os.path.join(HAL, 'Inc'),
    os.path.join(CMSISD, 'Include'),
    os.path.join(CMSIS, 'Include'),
    os.path.join(FRT, 'include'),
    os.path.join(FRT, 'portable', 'GCC', 'ARM_CM4F'),
]
INC_FLAGS = [f'-I{p}' for p in INCLUDES]


def glob_c(*parts):
    """列出目录下 .c 文件，排除 CubeMX 模板文件（*_template.c 不能直接编译）"""
    d = os.path.join(*parts)
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.endswith('.c') and not f.endswith('_template.c')]


SOURCES = []
SOURCES += glob_c(HERE, 'app', 'Core')
SOURCES += glob_c(HERE, 'app', 'protocol')
SOURCES += glob_c(HERE, 'app', 'drivers')
SOURCES += glob_c(HERE, 'app', 'control')
SOURCES += glob_c(HERE, 'app', 'services')
SOURCES += [os.path.join(HERE, f) for f in ('main.c', 'stm32f4xx_hal_msp.c', 'stm32f4xx_it.c')]
SOURCES += glob_c(HAL, 'Src')
SOURCES += [os.path.join(CMSISD, 'Source', 'Templates', 'system_stm32f4xx.c')]
SOURCES += [os.path.join(FRT, f) for f in
            ('tasks.c', 'queue.c', 'list.c', 'timers.c',
             'event_groups.c', 'stream_buffer.c', 'croutine.c')]
SOURCES += [os.path.join(FRT, 'portable', 'GCC', 'ARM_CM4F', 'port.c')]

STARTUP = os.path.join(HERE, 'startup_stm32f407xx.s')
LDSCRIPT = os.path.join(HERE, 'STM32F407ZGTX_FLASH.ld')


def run(cmd, **kw):
    print('  $', ' '.join(os.path.basename(c) for c in cmd[:3]), '...')
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        print(f'!! 命令失败 (exit {r.returncode})')
        sys.exit(1)
    if r.stderr.strip():
        # 警告不中断，但打印出来
        print(r.stderr.rstrip()[:3000])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clean', action='store_true')
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)
    if args.clean:
        for f in os.listdir(BUILD):
            os.remove(os.path.join(BUILD, f))
        print('[clean] 已清空 build/')

    # ---- 编译 ----
    objs = []
    t_start = os.times()
    for i, src in enumerate(SOURCES, 1):
        obj = os.path.join(BUILD, os.path.splitext(os.path.basename(src))[0] + '.o')
        objs.append(obj)
        tag = os.path.basename(os.path.dirname(os.path.dirname(src))) + '/' + os.path.basename(src)
        print(f'[{i:3d}/{len(SOURCES)}] CC {tag}')
        run([CC] + CFLAGS + INC_FLAGS + ['-MMD', '-MP', '-c', src, '-o', obj])

    # ---- 启动文件 ----
    startup_o = os.path.join(BUILD, 'startup_stm32f407xx.o')
    objs.append(startup_o)
    print(f'[AS ] startup_stm32f407xx.s')
    run([CC] + CPU + DEFS + ['-x', 'assembler-with-cpp', '-g3', '-c', STARTUP, '-o', startup_o])

    # ---- 链接 ----
    elf = os.path.join(BUILD, 'fw407.elf')
    print('[LD ] fw407.elf')
    run([CC] + CPU + ['--specs=nano.specs'] + objs +
        ['-T', LDSCRIPT,
         '-Wl,--gc-sections', f'-Wl,-Map={os.path.join(BUILD, "fw407.map")}',
         '-lc', '-lm', '-lnosys', '-o', elf])

    # ---- bin ----
    binf = os.path.join(BUILD, 'fw407.bin')
    run([CP, '-O', 'binary', elf, binf])

    # ---- 报告 ----
    r = subprocess.run([SZ, elf], capture_output=True, text=True)
    print()
    print(r.stdout.strip())
    print(f'\n构建完成: {binf}  ({os.path.getsize(binf)} bytes)')
    print(f'耗时 {os.times()[2]-t_start[2]:.1f}s')


if __name__ == '__main__':
    main()
