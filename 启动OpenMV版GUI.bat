@echo off
chcp 65001 >nul
title 植物病害检测系统 - OpenMV集成版
color 0A
cls

echo ==========================================
echo  🌿 植物病害智能检测系统 (OpenMV集成版)
echo ==========================================
echo.

:: 设置路径
set "PYTHON=C:\Users\lenovo\AppData\Local\KAIAssistant\AI\Tool_cache\resources\tools\win\python-3.11.9\python.exe"
set "PROJECT=E:\PlantDiseaseProject"
set "GUI_SCRIPT=%PROJECT%\gui\plant_disease_gui_openmv.py"

cd /d "%PROJECT%"

echo 项目路径: %PROJECT%
echo GUI脚本: %GUI_SCRIPT%
echo.

:: 检查Python
echo [1/4] 检查Python环境...
if not exist "%PYTHON%" (
    echo ❌ Python不存在
    pause
    exit /b 1
)
echo ✅ Python已找到

:: 检查串口库
echo.
echo [2/4] 检查串口库...
"%PYTHON%" -c "import serial" 2>nul
if errorlevel 1 (
    echo ⚠️ pyserial未安装，正在安装...
    "%PYTHON%" -m pip install pyserial -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
) else (
    echo ✅ pyserial已安装
)

:: 检查GUI脚本
echo.
echo [3/4] 检查GUI脚本...
if not exist "%GUI_SCRIPT%" (
    echo ❌ GUI脚本不存在: %GUI_SCRIPT%
    pause
    exit /b 1
)
echo ✅ GUI脚本已找到

:: 检查模型
echo.
echo [4/4] 检查模型文件...
set "MODEL=%PROJECT%\models\best.pt"
if exist "%MODEL%" (
    echo ✅ 模型已找到: %MODEL%
) else (
    echo ⚠️ 模型未找到: %MODEL%
    echo    OpenMV模式仍可运行，但无法进行检测
)

echo.
echo ==========================================
echo 启动GUI程序
echo ==========================================
echo.

:: 启动GUI
echo 正在启动植物病害检测GUI...
echo 功能：图片检测 + USB摄像头 + OpenMV串口
echo.

"%PYTHON%" "%GUI_SCRIPT%"

echo.
echo ==========================================
echo 程序已退出
echo ==========================================
pause
