@echo off
chcp 65001 >nul
color 0A
cls

echo ==========================================
echo    植物病害检测系统 - 启动器
echo ==========================================
echo.

:: 设置路径
set "PYTHON=C:\Users\lenovo\AppData\Local\KAIAssistant\AI\Tool_cache\resources\tools\win\python-3.11.9\python.exe"
set "PROJECT=E:\PlantDiseaseProject"
set "GUI_DIR=%PROJECT%\gui"

cd /d "%PROJECT%"

echo 项目路径: %PROJECT%
echo.

:: 检查Python
echo [1/3] 检查Python环境...
if not exist "%PYTHON%" (
    echo ✗ Python不存在: %PYTHON%
    pause
    exit /b 1
)
echo ✓ Python已找到

:: 检查模型
echo.
echo [2/3] 检查模型文件...
set "ONNX_MODEL=%PROJECT%\export\plant_disease.onnx"
set "YOLO_MODEL=%PROJECT%\models\best.pt"
set "ALT_MODEL=E:\YOLOv8_Projects\models\yolov8n.onnx"

if exist "%ONNX_MODEL%" (
    echo ✓ ONNX模型: %ONNX_MODEL%
    set "MODEL_TYPE=ONNX"
) else if exist "%ALT_MODEL%" (
    echo ✓ 替代ONNX模型: %ALT_MODEL%
    set "MODEL_TYPE=ONNX_ALT"
) else if exist "%YOLO_MODEL%" (
    echo ✓ YOLO模型: %YOLO_MODEL%
    set "MODEL_TYPE=YOLO"
) else (
    echo ⚠ 未找到专用模型，将尝试使用默认模型
    set "MODEL_TYPE=NONE"
)

:: 检查依赖
echo.
echo [3/3] 检查依赖库...

:: 检查OpenCV
"%PYTHON%" -c "import cv2; print('✓ OpenCV:', cv2.__version__)" 2>nul
if %errorlevel% neq 0 (
    echo ✗ OpenCV未安装，正在安装...
    "%PYTHON%" -m pip install opencv-python opencv-contrib-python -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
)

:: 检查PIL
"%PYTHON%" -c "from PIL import Image; print('✓ PIL已安装')" 2>nul
if %errorlevel% neq 0 (
    echo ✗ PIL未安装，正在安装...
    "%PYTHON%" -m pip install Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
)

:: 检查numpy
"%PYTHON%" -c "import numpy; print('✓ NumPy已安装')" 2>nul
if %errorlevel% neq 0 (
    echo ✗ NumPy未安装，正在安装...
    "%PYTHON%" -m pip install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
)

:: 尝试检查ultralytics (可选)
"%PYTHON%" -c "from ultralytics import YOLO; print('✓ ultralytics已安装')" 2>nul
if %errorlevel% neq 0 (
    echo ⚠ ultralytics未安装 (可选，ONNX模式不需要)
    echo   如需YOLOv8模式，请运行: pip install ultralytics
)

echo.
echo ==========================================
echo 启动选项
echo ==========================================
echo.
echo 请选择运行模式:
echo   [1] 启动GUI (自动选择ONNX/YOLOv8模式)
echo   [2] 训练新模型
echo   [3] 导出ONNX模型
echo   [4] 测试ONNX推理
echo   [5] 打开项目文件夹
echo   [Q] 退出
echo.

set /p choice="请选择 (1-5, Q): "

if "%choice%"=="1" goto START_GUI
if "%choice%"=="2" goto TRAIN
if "%choice%"=="3" goto EXPORT
if "%choice%"=="4" goto TEST
if "%choice%"=="5" goto OPEN_FOLDER
if /I "%choice%"=="Q" exit
goto MENU

:START_GUI
echo.
echo 启动GUI程序...
echo 使用模型类型: %MODEL_TYPE%
echo.

:: 使用新版GUI (支持ONNX和YOLOv8自动切换)
if exist "%GUI_DIR%\plant_disease_gui_v2.py" (
    "%PYTHON%" "%GUI_DIR%\plant_disease_gui_v2.py"
) else (
    echo ✗ 未找到GUI程序
    echo   请检查: %GUI_DIR%\plant_disease_gui_v2.py
    pause
)
goto END

:TRAIN
echo.
echo 启动训练程序...
if exist "%PROJECT%\train.py" (
    "%PYTHON%" "%PROJECT%\train.py"
) else (
    echo 请确保: %PROJECT%\train.py 存在
    pause
)
goto END

:EXPORT
echo.
echo 导出ONNX模型...
if exist "%PROJECT%\export_onnx.py" (
    "%PYTHON%" "%PROJECT%\export_onnx.py"
) else (
    echo 请确保: %PROJECT%\export_onnx.py 存在
    pause
)
goto END

:TEST
echo.
echo 测试ONNX推理...
if exist "%PROJECT%\onnx_inference.py" (
    "%PYTHON%" "%PROJECT%\onnx_inference.py" --model "%ONNX_MODEL%" --camera
) else (
    echo 请确保: %PROJECT%\onnx_inference.py 存在
    pause
)
goto END

:OPEN_FOLDER
echo.
echo 打开项目文件夹...
explorer "%PROJECT%"
goto END

:END
echo.
echo ==========================================
echo 程序已退出
echo ==========================================
pause
