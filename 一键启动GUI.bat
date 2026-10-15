@echo off
chcp 65001 >nul
title 植物病害检测系统 - 一键启动
color 0A
cls

echo ==========================================
echo    🌿 植物病害智能检测系统
echo ==========================================
echo.
echo  正在检查环境...
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 未找到Python
    echo    请安装Python 3.8或更高版本
    pause
    exit
)
echo ✅ Python已安装

:: 检查OpenCV
python -c "import cv2; print('✅ OpenCV:', cv2.__version__)" 2>nul
if errorlevel 1 (
    echo ⚠️ 警告: OpenCV未安装，正在安装...
    pip install opencv-python numpy pillow -q
)

:: 检查ultralytics
echo.
echo 检查ultralytics...
python -c "from ultralytics import YOLO; print('✅ YOLOv8可用')" 2>nul
if errorlevel 1 (
    echo ⚠️  YOLOv8未安装，将使用ONNX模式
    echo     (ONNX模式无需安装，可直接运行)
)

:: 检查模型
echo.
echo 检查模型文件...
if exist "E:\YOLOv8_Projects\models\yolov8n.onnx" (
    echo ✅ ONNX模型已就绪
) else (
    echo ⚠️  ONNX模型不存在，将自动下载...
)

echo.
echo ==========================================
echo    启动GUI程序
echo ==========================================
echo.
echo 请选择模式:
echo   [1] 推荐模式 - 自动检测 (V2修复版)
echo   [2] 原始版本 - 需要ultralytics
echo.

set /p choice="请选择 (1或2): "

if "%choice%"=="1" goto V2
if "%choice%"=="2" goto V1
goto V2

:V2
echo.
echo 启动 V2修复版 (自动兼容YOLOv8/ONNX)...
cd /d "E:\PlantDiseaseProject\gui"
python "plant_disease_gui_v2.py"
goto END

:V1
echo.
echo 启动原始版本...
cd /d "E:\PlantDiseaseProject\gui"
python "plant_disease_gui.py"
goto END

:END
echo.
echo 程序已关闭
pause
