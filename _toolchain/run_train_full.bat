@echo off
chcp 65001 >nul
cd /d E:\PlantDiseaseProject
"C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -u train_weed.py --data "E:\PlantDiseaseProject\datasets\weed_yolo\data.yaml" --epochs 100 --batch 8 --name weed_det --workers 4 > "E:\PlantDiseaseProject\runs\train_full.log" 2>&1
echo [exit] %ERRORLEVEL% >> "E:\PlantDiseaseProject\runs\train_full.log"
