@echo off
REM ============================================================
REM  训练杂草检测模型（GPU）
REM  用法:  _toolchain\run_train.bat [epochs] [batch]
REM  默认:  100 epoch / batch 8 / imgsz 640
REM  说明:  GTX 1660 SUPER 6GB，batch 8 + AMP 实测占用约 1.2GB，富余很大
REM ============================================================
setlocal
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PROJ=E:\PlantDiseaseProject"
set EPOCHS=%1
set BATCH=%2
if "%EPOCHS%"=="" set EPOCHS=100
if "%BATCH%"==""  set BATCH=8

cd /d "%PROJ%"
echo [train] 解释器: %PY%
echo [train] epochs=%EPOCHS% batch=%BATCH%
"%PY%" train_weed.py --data "%PROJ%\datasets\weed_yolo\data.yaml" --epochs %EPOCHS% --batch %BATCH% --name weed_det
if errorlevel 1 (
    echo [train] 失败，退出码 %errorlevel%
    exit /b 1
)
echo [train] 完成。权重: %PROJ%\models\weed_det\weights\best.pt
echo [train] 已复制到: %PROJ%\models\best.pt
endlocal
