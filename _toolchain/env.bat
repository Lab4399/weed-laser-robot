@echo off
REM ============================================================
REM  本机（开发机 CHINAMI-N0A8MK6）Python 环境入口
REM  用法：  call _toolchain\env.bat
REM  之后可直接用  %PY%  调用解释器
REM ============================================================
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PROJECT=E:\PlantDiseaseProject"

if not exist "%PY%" (
    echo [env] 解释器不存在: %PY%
    exit /b 1
)
echo [env] PY      = %PY%
echo [env] PROJECT = %PROJECT%
