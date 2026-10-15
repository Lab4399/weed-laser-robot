#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
植物病害检测 - 独立ONNX推理脚本
纯OpenCV实现，无需YOLOv8环境
可在工控机/边缘设备上运行

使用方法:
  # 单张图片
  python onnx_inference.py --model plant_disease.onnx --image test.jpg
  
  # 摄像头
  python onnx_inference.py --model plant_disease.onnx --camera
  
  # 批量处理
  python onnx_inference.py --model plant_disease.onnx --folder test_images/
"""

import cv2
import numpy as np
import argparse
import os
import time
import glob

# 类别名称 (与训练时一致)
CLASS_NAMES = {
    0: '番茄早疫病',
    1: '番茄晚疫病',
    2: '番茄叶霉病',
    3: '番茄斑点病',
    4: '番茄黄化病毒',
    5: '草莓叶枯病',
    6: '南瓜白粉病',
    7: '玉米叶斑病',
    8: '土豆晚疫病',
    9: '健康叶片'
}

# 颜色 (BGR格式，用于OpenCV)
COLORS = [
    (0, 0, 255),      # 红
    (255, 0, 0),      # 蓝
    (0, 255, 0),      # 绿
    (0, 255, 255),    # 黄
    (255, 0, 255),    # 紫
    (255, 255, 0),    # 青
    (0, 0, 128),      # 深红
    (0, 128, 0),      # 深绿
    (0, 128, 128),    # 橄榄
    (128, 128, 128)   # 灰
]


class ONNXPlantDiseaseDetector:
    """
    植物病害检测器 - ONNX版本
    纯OpenCV实现，无需YOLOv8
    """
    
    def __init__(self, model_path, input_size=640, conf_thres=0.25, iou_thres=0.45):
        """
        初始化检测器
        
        Args:
            model_path: ONNX模型路径
            input_size: 输入图像尺寸
            conf_thres: 置信度阈值
            iou_thres: NMS IoU阈值
        """
        self.input_size = input_size
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        
        # 加载ONNX模型
        print(f"加载模型: {model_path}")
        self.net = cv2.dnn.readNet(model_path)
        
        # 设置计算后端
        # 尝试CUDA加速
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            print("使用CUDA加速")
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
        else:
            print("使用CPU推理")
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        
        print(f"✓ 模型加载完成")
        print(f"  输入尺寸: {input_size}x{input_size}")
    
    def preprocess(self, img):
        """
        预处理图像 - LetterBox
        """
        self.img_height, self.img_width = img.shape[:2]
        
        # 计算缩放比例
        scale = min(self.input_size / self.img_width, 
                    self.input_size / self.img_height)
        
        # 计算新尺寸
        new_w = int(self.img_width * scale)
        new_h = int(self.img_height * scale)
        
        # 缩放图像
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # 创建填充画布
        pad_img = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        
        # 计算填充位置
        pad_x = (self.input_size - new_w) // 2
        pad_y = (self.input_size - new_h) // 2
        
        # 放置图像
        pad_img[pad_y:pad_y+new_h, pad_x:pad_x+new_w] = resized
        
        # 保存填充信息用于后处理
        self.scale = scale
        self.pad_x = pad_x
        self.pad_y = pad_y
        
        # 归一化并转Blob
        blob = cv2.dnn.blobFromImage(
            pad_img, 
            1/255.0, 
            (self.input_size, self.input_size),
            swapRB=True,
            crop=False
        )
        
        return blob
    
    def postprocess(self, outputs):
        """
        后处理 - 解析输出并NMS
        """
        # 转置为 [8400, 84]
        predictions = np.squeeze(outputs[0]).T
        
        # 过滤低置信度
        scores = np.max(predictions[:, 4:], axis=1)
        valid_mask = scores > self.conf_thres
        predictions = predictions[valid_mask]
        scores = scores[valid_mask]
        
        if len(predictions) == 0:
            return [], [], []
        
        # 提取框坐标
        boxes = predictions[:, :4]
        class_ids = np.argmax(predictions[:, 4:], axis=1)
        
        # xywh 转 xyxy
        xyxy_boxes = np.zeros_like(boxes)
        xyxy_boxes[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        xyxy_boxes[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        xyxy_boxes[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        xyxy_boxes[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
        
        # NMS
        indices = cv2.dnn.NMSBoxes(
            xyxy_boxes.tolist(),
            scores.tolist(),
            self.conf_thres,
            self.iou_thres
        )
        
        if len(indices) == 0:
            return [], [], []
        
        boxes = xyxy_boxes[indices.flatten()]
        scores = scores[indices.flatten()]
        class_ids = class_ids[indices.flatten()]
        
        return boxes, scores, class_ids
    
    def scale_boxes(self, boxes):
        """
        将框坐标映射回原图
        """
        scaled_boxes = []
        for box in boxes:
            x1, y1, x2, y2 = box
            
            # 去除填充并缩放
            x1 = (x1 - self.pad_x) / self.scale
            y1 = (y1 - self.pad_y) / self.scale
            x2 = (x2 - self.pad_x) / self.scale
            y2 = (y2 - self.pad_y) / self.scale
            
            # 限制在图像范围内
            x1 = max(0, min(x1, self.img_width))
            y1 = max(0, min(y1, self.img_height))
            x2 = max(0, min(x2, self.img_width))
            y2 = max(0, min(y2, self.img_height))
            
            scaled_boxes.append([int(x1), int(y1), int(x2), int(y2)])
        
        return scaled_boxes
    
    def draw_detections(self, img, boxes, scores, class_ids):
        """
        绘制检测结果
        """
        result = img.copy()
        
        for box, score, class_id in zip(boxes, scores, class_ids):
            x1, y1, x2, y2 = box
            
            # 获取颜色和类别名
            color = COLORS[class_id % len(COLORS)]
            class_name = CLASS_NAMES.get(class_id, f'Class {class_id}')
            
            # 绘制矩形框
            cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
            
            # 准备标签
            label = f"{class_name}: {score:.2f}"
            
            # 计算标签尺寸
            (text_w, text_h), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1
            )
            
            # 绘制标签背景
            label_y = y1 - text_h - 10 if y1 - text_h - 10 > 0 else y1 + 10
            cv2.rectangle(
                result,
                (x1, label_y),
                (x1 + text_w + 10, label_y + text_h + 5),
                color,
                -1
            )
            
            # 绘制文字
            cv2.putText(
                result, label, (x1 + 5, label_y + text_h),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1
            )
        
        return result
    
    def detect(self, img, draw=True):
        """
        检测图像
        
        Returns:
            result_img: 绘制结果的图像
            boxes: 检测框 [x1, y1, x2, y2]
            scores: 置信度
            class_ids: 类别ID
        """
        # 预处理
        blob = self.preprocess(img)
        
        # 推理
        self.net.setInput(blob)
        outputs = self.net.forward()
        
        # 后处理
        boxes, scores, class_ids = self.postprocess(outputs)
        
        if len(boxes) == 0:
            return img, [], [], []
        
        # 坐标映射
        boxes = self.scale_boxes(boxes)
        
        # 绘制
        if draw:
            result = self.draw_detections(img, boxes, scores, class_ids)
        else:
            result = img
        
        return result, boxes, scores, class_ids


def detect_image(detector, image_path, output_path=None, show=True):
    """检测单张图片"""
    print(f"\n检测图片: {image_path}")
    
    # 读取图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"✗ 无法读取图片: {image_path}")
        return
    
    # 检测
    start_time = time.time()
    result, boxes, scores, class_ids = detector.detect(img)
    inference_time = time.time() - start_time
    
    # 打印结果
    print(f"  推理时间: {inference_time*1000:.1f} ms")
    print(f"  检测到: {len(boxes)} 个目标")
    
    for i, (box, score, cls_id) in enumerate(zip(boxes, scores, class_ids)):
        name = CLASS_NAMES.get(cls_id, f'Class {cls_id}')
        print(f"    [{i+1}] {name}: {score:.3f}")
    
    # 保存结果
    if output_path:
        cv2.imwrite(output_path, result)
        print(f"  ✓ 结果已保存: {output_path}")
    
    # 显示结果
    if show:
        cv2.imshow('Detection Result', result)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    
    return result


def detect_camera(detector, camera_id=0):
    """摄像头实时检测"""
    print(f"\n启动摄像头 (ID: {camera_id})")
    print("按 'q' 退出，按 's' 保存截图")
    
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print(f"✗ 无法打开摄像头 {camera_id}")
        return
    
    # 获取摄像头属性
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"  分辨率: {width}x{height}, FPS: {fps}")
    
    frame_count = 0
    start_time = time.time()
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        
        # 检测
        result, boxes, scores, class_ids = detector.detect(frame)
        
        # 显示FPS
        elapsed = time.time() - start_time
        current_fps = frame_count / elapsed if elapsed > 0 else 0
        cv2.putText(
            result, f'FPS: {current_fps:.1f}',
            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
        )
        
        # 显示检测数
        cv2.putText(
            result, f'Detected: {len(boxes)}',
            (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
        )
        
        # 显示
        cv2.imshow('Plant Disease Detection', result)
        
        # 按键处理
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            save_path = f'screenshot_{time.strftime(\"%Y%m%d_%H%M%S\")}.jpg'
            cv2.imwrite(save_path, result)
            print(f"  截图已保存: {save_path}")
    
    cap.release()
    cv2.destroyAllWindows()
    print(f"\n  共处理 {frame_count} 帧")


def detect_folder(detector, folder_path, output_folder=None):
    """批量检测文件夹"""
    print(f"\n批量检测文件夹: {folder_path}")
    
    # 获取所有图片
    image_paths = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp']:
        image_paths.extend(glob.glob(os.path.join(folder_path, ext)))
    
    if not image_paths:
        print("✗ 未找到图片文件")
        return
    
    print(f"  找到 {len(image_paths)} 张图片")
    
    # 创建输出目录
    if output_folder:
        os.makedirs(output_folder, exist_ok=True)
    
    # 批量检测
    for i, img_path in enumerate(image_paths, 1):
        print(f"\n[{i}/{len(image_paths)}] {os.path.basename(img_path)}")
        
        if output_folder:
            output_path = os.path.join(
                output_folder,
                f"result_{os.path.basename(img_path)}"
            )
        else:
            output_path = None
        
        detect_image(detector, img_path, output_path, show=False)
    
    print(f"\n✓ 批量检测完成")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Plant Disease Detection - ONNX')
    
    parser.add_argument('--model', type=str,
                        default=r'E:\PlantDiseaseProject\export\plant_disease.onnx',
                        help='ONNX模型路径')
    
    parser.add_argument('--image', type=str,
                        help='检测单张图片')
    
    parser.add_argument('--camera', action='store_true',
                        help='使用摄像头实时检测')
    
    parser.add_argument('--folder', type=str,
                        help='批量检测文件夹')
    
    parser.add_argument('--output', type=str,
                        help='输出图片路径')
    
    parser.add_argument('--imgsz', type=int, default=640,
                        help='输入图像尺寸')
    
    parser.add_argument('--conf', type=float, default=0.25,
                        help='置信度阈值')
    
    parser.add_argument('--iou', type=float, default=0.45,
                        help='NMS IoU阈值')
    
    args = parser.parse_args()
    
    # 检查模型
    if not os.path.exists(args.model):
        print(f"✗ 模型文件不存在: {args.model}")
        print(f"请先用 export_onnx.py 导出模型")
        return
    
    print('='*60)
    print('植物病害检测 - ONNX推理')
    print('='*60)
    print(f'模型: {args.model}')
    print(f'输入尺寸: {args.imgsz}')
    print(f'置信度: {args.conf}')
    print('='*60)
    
    # 创建检测器
    detector = ONNXPlantDiseaseDetector(
        args.model,
        input_size=args.imgsz,
        conf_thres=args.conf,
        iou_thres=args.iou
    )
    
    # 执行检测
    if args.image:
        detect_image(detector, args.image, args.output)
    elif args.camera:
        detect_camera(detector)
    elif args.folder:
        detect_folder(detector, args.folder, args.output)
    else:
        print('\n请指定检测模式:')
        print('  --image <图片路径>    检测单张图片')
        print('  --camera              使用摄像头')
        print('  --folder <文件夹>     批量检测')
        print('\n示例:')
        print('  python onnx_inference.py --model plant_disease.onnx --image test.jpg')
        print('  python onnx_inference.py --model plant_disease.onnx --camera')


if __name__ == '__main__':
    main()
