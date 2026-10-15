#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
植物病害检测 GUI 程序 (修复版)
支持两种模式:
  模式1: YOLOv8 (ultralytics) - 功能完整
  模式2: ONNX (OpenCV) - 无需ultralytics，独立运行

使用方法:
  python plant_disease_gui_v2.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import cv2
import numpy as np
import threading
import os
import sys
import time
import glob

# ==================== 配置 ====================
PROJECT_DIR = r'E:\PlantDiseaseProject'
ONNX_MODEL_PATH = os.path.join(PROJECT_DIR, 'export', 'plant_disease.onnx')
YOLO_MODEL_PATH = os.path.join(PROJECT_DIR, 'models', 'best.pt')

# 类别定义
CLASS_NAMES = {
    0: '番茄早疫病', 1: '番茄晚疫病', 2: '番茄叶霉病',
    3: '番茄斑点病', 4: '番茄黄化病毒', 5: '草莓叶枯病',
    6: '南瓜白粉病', 7: '玉米叶斑病', 8: '土豆晚疫病', 9: '健康叶片'
}

COLORS = [
    (255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 0),
    (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0),
    (128, 128, 0), (128, 128, 128)
]

# ==================== 检测器基类 ====================
class BaseDetector:
    """检测器基类"""
    
    def __init__(self):
        self.class_names = CLASS_NAMES
        self.colors = COLORS
    
    def detect(self, image, conf_thres=0.25):
        """子类必须实现"""
        raise NotImplementedError
    
    def draw_detections(self, img, boxes, scores, class_ids):
        """绘制检测结果 (OpenCV版本)"""
        result = img.copy()
        
        for box, score, class_id in zip(boxes, scores, class_ids):
            x1, y1, x2, y2 = map(int, box)
            color = self.colors[class_id % len(self.colors)]
            class_name = self.class_names.get(class_id, f'Class {class_id}')
            
            # 绘制框
            cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
            
            # 标签
            label = f"{class_name}: {score:.2f}"
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            label_y = max(y1 - text_h - 5, text_h + 5)
            
            cv2.rectangle(result, (x1, label_y), (x1 + text_w + 10, label_y + text_h + 5), color, -1)
            cv2.putText(result, label, (x1 + 5, label_y + text_h), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        return result

# ==================== ONNX检测器 ====================
class ONNXDetector(BaseDetector):
    """ONNX检测器 - 无需ultralytics"""
    
    def __init__(self, model_path, input_size=640):
        super().__init__()
        self.input_size = input_size
        self.model_path = model_path
        self.net = None
        self.load_model()
    
    def load_model(self):
        """加载ONNX模型"""
        if not os.path.exists(self.model_path):
            # 尝试使用YOLOv8预训练模型
            alt_path = r'E:\YOLOv8_Projects\models\yolov8n.onnx'
            if os.path.exists(alt_path):
                self.model_path = alt_path
                print(f"使用替代模型: {alt_path}")
            else:
                raise FileNotFoundError(f"模型不存在: {self.model_path}")
        
        print(f"加载ONNX模型: {self.model_path}")
        self.net = cv2.dnn.readNet(self.model_path)
        
        # 尝试CUDA加速
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            print("使用CUDA加速")
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
        else:
            print("使用CPU推理")
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    
    def preprocess(self, img):
        """预处理图像"""
        self.img_height, self.img_width = img.shape[:2]
        
        # LetterBox
        scale = min(self.input_size / self.img_width, self.input_size / self.img_height)
        new_w, new_h = int(self.img_width * scale), int(self.img_height * scale)
        
        resized = cv2.resize(img, (new_w, new_h))
        pad_img = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        
        self.pad_x = (self.input_size - new_w) // 2
        self.pad_y = (self.input_size - new_h) // 2
        pad_img[self.pad_y:self.pad_y+new_h, self.pad_x:self.pad_x+new_w] = resized
        
        self.scale = scale
        
        # 转blob
        blob = cv2.dnn.blobFromImage(pad_img, 1/255.0, (self.input_size, self.input_size), swapRB=True)
        return blob
    
    def postprocess(self, outputs, conf_thres=0.25, iou_thres=0.45):
        """后处理"""
        predictions = np.squeeze(outputs[0]).T
        
        # 过滤低置信度
        scores = np.max(predictions[:, 4:], axis=1)
        valid_mask = scores > conf_thres
        predictions = predictions[valid_mask]
        scores = scores[valid_mask]
        
        if len(predictions) == 0:
            return [], [], []
        
        boxes = predictions[:, :4]
        class_ids = np.argmax(predictions[:, 4:], axis=1)
        
        # xywh -> xyxy
        xyxy = np.zeros_like(boxes)
        xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
        
        # NMS
        indices = cv2.dnn.NMSBoxes(xyxy.tolist(), scores.tolist(), conf_thres, iou_thres)
        
        if len(indices) == 0:
            return [], [], []
        
        boxes = xyxy[indices.flatten()]
        scores = scores[indices.flatten()]
        class_ids = class_ids[indices.flatten()]
        
        return boxes, scores, class_ids
    
    def scale_boxes(self, boxes):
        """坐标映射回原图"""
        scaled = []
        for box in boxes:
            x1, y1, x2, y2 = box
            x1 = max(0, min((x1 - self.pad_x) / self.scale, self.img_width))
            y1 = max(0, min((y1 - self.pad_y) / self.scale, self.img_height))
            x2 = max(0, min((x2 - self.pad_x) / self.scale, self.img_width))
            y2 = max(0, min((y2 - self.pad_y) / self.scale, self.img_height))
            scaled.append([x1, y1, x2, y2])
        return scaled
    
    def detect(self, image, conf_thres=0.25):
        """检测图像"""
        # 预处理
        blob = self.preprocess(image)
        
        # 推理
        self.net.setInput(blob)
        outputs = self.net.forward()
        
        # 后处理
        boxes, scores, class_ids = self.postprocess(outputs, conf_thres)
        
        if len(boxes) == 0:
            return image, [], [], []
        
        boxes = self.scale_boxes(boxes)
        result = self.draw_detections(image, boxes, scores, class_ids)
        
        return result, boxes, scores, class_ids

# ==================== YOLOv8检测器 ====================
class YOLODetector(BaseDetector):
    """YOLOv8检测器 - 需要ultralytics"""
    
    def __init__(self, model_path):
        super().__init__()
        self.model_path = model_path
        self.model = None
        self.load_model()
    
    def load_model(self):
        """加载YOLOv8模型"""
        from ultralytics import YOLO
        
        if not os.path.exists(self.model_path):
            # 尝试使用默认模型
            alt_paths = [
                r'E:\YOLOv8_Projects\models\yolov8n.pt',
                r'E:\PlantDiseaseProject\models\best.pt',
            ]
            for path in alt_paths:
                if os.path.exists(path):
                    self.model_path = path
                    break
            else:
                raise FileNotFoundError(f"模型不存在: {self.model_path}")
        
        print(f"加载YOLOv8模型: {self.model_path}")
        self.model = YOLO(self.model_path)
    
    def detect(self, image, conf_thres=0.25):
        """检测图像"""
        results = self.model(image, conf=conf_thres, verbose=False)[0]
        
        boxes = results.boxes.xyxy.cpu().numpy() if len(results.boxes) > 0 else []
        scores = results.boxes.conf.cpu().numpy() if len(results.boxes) > 0 else []
        class_ids = results.boxes.cls.cpu().numpy().astype(int) if len(results.boxes) > 0 else []
        
        if len(boxes) == 0:
            return image, [], [], []
        
        result = self.draw_detections(image, boxes, scores, class_ids)
        return result, boxes, scores, class_ids

# ==================== GUI主程序 ====================
class PlantDiseaseGUI:
    """植物病害检测GUI"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("🌿 植物病害智能检测系统")
        self.root.geometry("1200x800")
        
        # 初始化变量
        self.detector = None
        self.detector_type = None
        self.cap = None
        self.is_camera_running = False
        self.current_image = None
        
        # 尝试加载检测器
        self.init_detector()
        
        # 创建界面
        self.create_ui()
    
    def init_detector(self):
        """初始化检测器 (自动选择模式)"""
        # 首先尝试ONNX (不需要ultralytics)
        try:
            self.detector = ONNXDetector(ONNX_MODEL_PATH)
            self.detector_type = "ONNX"
            print("✅ 使用ONNX模式")
            return
        except Exception as e:
            print(f"⚠️ ONNX加载失败: {e}")
        
        # 然后尝试YOLOv8
        try:
            self.detector = YOLODetector(YOLO_MODEL_PATH)
            self.detector_type = "YOLOv8"
            print("✅ 使用YOLOv8模式")
            return
        except ImportError as e:
            print(f"⚠️ YOLOv8不可用: {e}")
        except Exception as e:
            print(f"⚠️ YOLOv8加载失败: {e}")
        
        # 都失败了
        self.detector = None
        self.detector_type = None
        print("❌ 无法加载任何检测器")
    
    def create_ui(self):
        """创建用户界面"""
        # 主框架
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title = ttk.Label(main, text="🌿 植物病害智能检测系统", 
                         font=('Microsoft YaHei', 20, 'bold'))
        title.pack(pady=10)
        
        # 模式显示
        mode_text = f"当前模式: {self.detector_type if self.detector else '未加载'}"
        self.mode_label = ttk.Label(main, text=mode_text, 
                                   font=('Microsoft YaHei', 12))
        self.mode_label.pack()
        
        # 左右分栏
        paned = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 左侧面板
        left = ttk.LabelFrame(paned, text="控制面板", padding=10)
        paned.add(left, weight=1)
        
        # 右侧面板
        right = ttk.LabelFrame(paned, text="检测结果", padding=10)
        paned.add(right, weight=3)
        
        # ===== 左侧面板内容 =====
        
        # 状态
        status_frame = ttk.LabelFrame(left, text="系统状态", padding=5)
        status_frame.pack(fill=tk.X, pady=5)
        
        if self.detector:
            status_text = f"✅ 检测器就绪\n类型: {self.detector_type}"
            status_color = 'green'
        else:
            status_text = "❌ 检测器未加载\n请检查模型文件"
            status_color = 'red'
        
        self.status_label = ttk.Label(status_frame, text=status_text,
                                     foreground=status_color)
        self.status_label.pack(anchor=tk.W)
        
        # 图片检测
        img_frame = ttk.LabelFrame(left, text="图片检测", padding=5)
        img_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(img_frame, text="📁 选择图片", 
                  command=self.select_image).pack(fill=tk.X, pady=2)
        
        ttk.Button(img_frame, text="💾 保存结果", 
                  command=self.save_result).pack(fill=tk.X, pady=2)
        
        # 摄像头
        cam_frame = ttk.LabelFrame(left, text="摄像头检测", padding=5)
        cam_frame.pack(fill=tk.X, pady=10)
        
        self.cam_btn = ttk.Button(cam_frame, text="📷 打开摄像头",
                                   command=self.toggle_camera)
        self.cam_btn.pack(fill=tk.X)
        
        # 参数
        param_frame = ttk.LabelFrame(left, text="检测参数", padding=5)
        param_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(param_frame, text="置信度阈值:").pack(anchor=tk.W)
        self.conf_var = tk.DoubleVar(value=0.25)
        self.conf_slider = ttk.Scale(param_frame, from_=0.1, to=0.9,
                                    variable=self.conf_var, orient=tk.HORIZONTAL)
        self.conf_slider.pack(fill=tk.X)
        self.conf_label = ttk.Label(param_frame, text="0.25")
        self.conf_label.pack(anchor=tk.W)
        self.conf_slider.bind('<Motion>', lambda e: self.conf_label.config(text=f"{self.conf_var.get():.2f}"))
        
        # 结果统计
        stats_frame = ttk.LabelFrame(left, text="检测统计", padding=5)
        stats_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.stats_text = scrolledtext.ScrolledText(stats_frame, height=10, wrap=tk.WORD)
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self.stats_text.insert(tk.END, "等待检测...\n")
        
        # ===== 右侧面板内容 =====
        
        self.image_label = ttk.Label(right, text="请选择图片或打开摄像头")
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # 帮助按钮
        ttk.Button(left, text="❓ 使用帮助", 
                  command=self.show_help).pack(fill=tk.X, pady=5)
    
    def select_image(self):
        """选择图片检测"""
        if not self.detector:
            messagebox.showerror("错误", "检测器未加载，请检查模型文件")
            return
        
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp"), ("所有文件", "*.*")]
        )
        
        if not path:
            return
        
        self.run_detection(path)
    
    def run_detection(self, image_path):
        """运行检测"""
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, f"检测中...\n图片: {os.path.basename(image_path)}\n")
        self.root.update()
        
        def detect_thread():
            try:
                # 读取图片
                img = cv2.imread(image_path)
                if img is None:
                    self.root.after(0, lambda: messagebox.showerror("错误", "无法读取图片"))
                    return
                
                # 检测
                start = time.time()
                result, boxes, scores, class_ids = self.detector.detect(img, self.conf_var.get())
                elapsed = time.time() - start
                
                # 保存结果
                self.current_image = result
                
                # 显示图片
                self.show_image(result)
                
                # 更新统计
                self.update_stats(elapsed, boxes, scores, class_ids)
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
        
        threading.Thread(target=detect_thread, daemon=True).start()
    
    def show_image(self, cv_image):
        """显示图片"""
        if len(cv_image.shape) == 3:
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        
        # 调整大小
        h, w = cv_image.shape[:2]
        max_size = 800
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            cv_image = cv2.resize(cv_image, (int(w*scale), int(h*scale)))
        
        # 转PIL
        pil_img = Image.fromarray(cv_image)
        photo = ImageTk.PhotoImage(pil_img)
        
        self.image_label.config(image=photo)
        self.image_label.image = photo
    
    def update_stats(self, elapsed, boxes, scores, class_ids):
        """更新统计"""
        self.stats_text.delete(1.0, tk.END)
        
        self.stats_text.insert(tk.END, f"⏱️ 推理时间: {elapsed*1000:.1f} ms\n")
        self.stats_text.insert(tk.END, f"📦 检测目标: {len(boxes)} 个\n")
        self.stats_text.insert(tk.END, "-" * 30 + "\n")
        
        # 统计各类别
        from collections import Counter
        class_counts = Counter(class_ids)
        
        for i, (cls_id, box, score) in enumerate(zip(class_ids, boxes, scores)):
            name = CLASS_NAMES.get(cls_id, f'Class {cls_id}')
            self.stats_text.insert(tk.END, f"[{i+1}] {name}: {score:.3f}\n")
    
    def save_result(self):
        """保存结果"""
        if self.current_image is None:
            messagebox.showwarning("警告", "没有可保存的结果")
            return
        
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png")]
        )
        
        if path:
            cv2.imwrite(path, self.current_image)
            messagebox.showinfo("成功", f"已保存: {path}")
    
    def toggle_camera(self):
        """切换摄像头"""
        if not self.detector:
            messagebox.showerror("错误", "检测器未加载")
            return
        
        if self.is_camera_running:
            self.stop_camera()
        else:
            self.start_camera()
    
    def start_camera(self):
        """启动摄像头"""
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            messagebox.showerror("错误", "无法打开摄像头")
            return
        
        self.is_camera_running = True
        self.cam_btn.config(text="⏹️ 关闭摄像头")
        
        threading.Thread(target=self.camera_loop, daemon=True).start()
    
    def stop_camera(self):
        """停止摄像头"""
        self.is_camera_running = False
        if self.cap:
            self.cap.release()
        self.cam_btn.config(text="📷 打开摄像头")
        self.image_label.config(text="请选择图片或打开摄像头")
    
    def camera_loop(self):
        """摄像头循环"""
        frame_count = 0
        last_time = time.time()
        
        while self.is_camera_running:
            ret, frame = self.cap.read()
            if not ret:
                break
            
            frame_count += 1
            
            # 每3帧检测一次
            if frame_count % 3 == 0:
                result, boxes, scores, class_ids = self.detector.detect(frame, self.conf_var.get())
                
                # 显示FPS
                fps = 1 / (time.time() - last_time) if last_time else 0
                last_time = time.time()
                
                cv2.putText(result, f"FPS: {fps:.1f}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(result, f"Objects: {len(boxes)}", (10, 70),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                self.root.after(0, lambda img=result: self.show_image(img))
                self.root.after(0, lambda: self.stats_text.delete(1.0, tk.END) or 
                                         self.stats_text.insert(tk.END, f"实时检测中...\nFPS: {fps:.1f}\nObjects: {len(boxes)}"))
            else:
                self.root.after(0, lambda img=frame: self.show_image(img))
    
    def show_help(self):
        """显示帮助"""
        help_text = """
植物病害检测系统 - 使用帮助

【模式说明】
系统会自动选择可用模式:
- ONNX模式: 无需额外安装，使用OpenCV直接运行
- YOLOv8模式: 需要ultralytics库，功能更完整

【功能说明】
1. 图片检测: 选择本地图片进行病害识别
2. 摄像头检测: 实时检测摄像头画面
3. 置信度调整: 滑动条调整检测阈值(0.1-0.9)

【快捷键】
- 摄像头模式按Q退出

【常见问题】
Q: 提示"检测器未加载"
A: 请确保模型文件存在:
   - ONNX模型: export/plant_disease.onnx
   - YOLO模型: models/best.pt

Q: 摄像头无法打开
A: 请检查摄像头连接和权限

Q: 检测速度慢
A: 这是正常的(CPU模式约100-200ms/帧)
如需加速，可考虑使用GPU
        """
        messagebox.showinfo("使用帮助", help_text)

def main():
    root = tk.Tk()
    app = PlantDiseaseGUI(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_camera() if app.is_camera_running else None, root.destroy()))
    
    print("="*60)
    print("植物病害智能检测系统")
    print("="*60)
    print(f"检测器: {app.detector_type if app.detector else '未加载'}")
    print("="*60)
    
    root.mainloop()

if __name__ == '__main__':
    main()
