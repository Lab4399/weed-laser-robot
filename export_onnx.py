#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
植物病害检测 - ONNX导出脚本
将训练好的YOLOv8模型导出为ONNX格式

使用方法:
  python export_onnx.py --model models/plant_disease_exp1/weights/best.pt
"""

import argparse
import os
import sys

def parse_args():
    parser = argparse.ArgumentParser(description='Export YOLOv8 to ONNX')
    
    parser.add_argument('--model', type=str,
                        default=r'E:\PlantDiseaseProject\models\plant_disease_exp1\weights\best.pt',
                        help='训练好的模型路径')
    
    parser.add_argument('--output', type=str,
                        default=r'E:\PlantDiseaseProject\export\plant_disease.onnx',
                        help='输出ONNX路径')
    
    parser.add_argument('--imgsz', type=int, default=640,
                        help='输入图像尺寸')
    
    parser.add_argument('--simplify', action='store_true', default=True,
                        help='简化ONNX模型')
    
    return parser.parse_args()

def main():
    args = parse_args()
    
    print('='*60)
    print('YOLOv8 ONNX 导出')
    print('='*60)
    
    # 检查模型文件
    if not os.path.exists(args.model):
        print(f'✗ 模型文件不存在: {args.model}')
        print('请检查路径或先训练模型')
        sys.exit(1)
    
    print(f'输入模型: {args.model}')
    print(f'输出ONNX: {args.output}')
    print(f'图像尺寸: {args.imgsz}')
    print(f'简化模型: {args.simplify}')
    print('-'*60)
    
    try:
        from ultralytics import YOLO
        
        # 加载模型
        print('\n[1/3] 加载模型...')
        model = YOLO(args.model)
        print('✓ 模型加载成功')
        
        # 导出ONNX
        print('\n[2/3] 导出ONNX...')
        onnx_path = model.export(
            format='onnx',
            imgsz=args.imgsz,
            simplify=args.simplify,
            dynamic=False,
            opset=12
        )
        
        print(f'✓ ONNX导出成功')
        print(f'  路径: {onnx_path}')
        
        # 复制到指定输出路径
        if onnx_path != args.output:
            import shutil
            shutil.copy(onnx_path, args.output)
            print(f'✓ 已复制到: {args.output}')
        
        # 获取文件大小
        size_mb = os.path.getsize(args.output) / 1024 / 1024
        print(f'  大小: {size_mb:.1f} MB')
        
        # 验证ONNX
        print('\n[3/3] 验证ONNX...')
        try:
            import onnx
            onnx_model = onnx.load(args.output)
            onnx.checker.check_model(onnx_model)
            print('✓ ONNX模型验证通过')
        except Exception as e:
            print(f'⚠ ONNX验证警告: {e}')
        
        print('\n' + '='*60)
        print('导出完成!')
        print('='*60)
        print(f'\n使用说明:')
        print(f'  python onnx_inference.py --model {args.output}')
        print('='*60)
        
    except Exception as e:
        print(f'\n✗ 导出失败: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
