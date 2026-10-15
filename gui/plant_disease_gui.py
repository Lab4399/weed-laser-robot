#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
植物病害检测 GUI 程序
功能：
  1. 图片选择识别
  2. 摄像头实时检测
  3. 结果可视化（框+标签）
  4. 模型切换

使用方法：
  python plant_disease_gui.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk, ImageDraw, ImageFont
import cv2
import numpy as np
import threading
import os
import sys
import time
import subprocess

# 添加YOLOv8路径
sys.path.append(r'E:\YOLOv8_Projects\src')

# 延迟导入ultralytics
YOLO = None
try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None
    print("⚠️ 警告: 未找到ultralytics模块，将使用ONNX模式")

class PlantDiseaseDetector:
    """植物病害检测器类"""
    
    def __init__(self, model_path):
        """初始化检测器"""
        self.model_path = model_path
        self.model = None
        self.class_names = {
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
        self.colors = [
            (255, 0, 0),    # 红 - 早疫病
            (0, 0, 255),    # 蓝 - 晚疫病
            (0, 255, 0),    # 绿 - 叶霉病
            (255, 255, 0),  # 黄 - 斑点病
            (255, 0, 255),  # 紫 - 黄化病毒
            (0, 255, 255),  # 青 - 草莓
            (128, 0, 0),    # 深红 - 南瓜
            (0, 128, 0),    # 深绿 - 玉米
            (128, 128, 0),  # 橄榄 - 土豆
            (128, 128, 128) # 灰 - 健康
        ]
        
    def load_model(self):
        """加载YOLOv8模型"""
        global YOLO
        
        # 如果YOLO未导入，尝试重新导入
        if YOLO is None:
            try:
                from ultralytics import YOLO
            except ImportError:
                return False, "ultralytics未安装，请先安装: pip install ultralytics"
        
        try:
            self.model = YOLO(self.model_path)
            print(f"✓ 模型加载成功: {self.model_path}")
            return True, None
        except Exception as e:
            error_msg = f"模型加载失败: {str(e)}"
            print(f"✗ {error_msg}")
            return False, error_msg
    
    def detect(self, image_path, conf_thres=0.25):
        """检测图片"""
        if self.model is None:
            return None, "模型未加载"
        
        try:
            results = self.model(image_path, conf=conf_thres, verbose=False)
            return results[0], None
        except Exception as e:
            return None, str(e)
    
    def draw_results(self, image, result):
        """绘制检测结果"""
        if result is None or len(result.boxes) == 0:
            return image
        
        # 转换为PIL Image
        if isinstance(image, str):
            img = Image.open(image).convert('RGB')
        else:
            img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        
        draw = ImageDraw.Draw(img)
        
        # 获取框和标签
        boxes = result.boxes
        
        for box in boxes:
            # 获取框坐标
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # 获取类别和置信度
            cls_id = int(box.cls)
            conf = float(box.conf)
            
            # 获取颜色
            color = self.colors[cls_id % len(self.colors)]
            
            # 绘制矩形框
            draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
            
            # 准备标签
            label = f"{self.class_names.get(cls_id, f'Class {cls_id}')}: {conf:.2f}"
            
            # 计算标签位置
            text_bbox = draw.textbbox((0, 0), label)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            # 绘制标签背景
            label_y = y1 - text_height - 5 if y1 - text_height - 5 > 0 else y1 + 5
            draw.rectangle(
                [x1, label_y, x1 + text_width + 10, label_y + text_height + 5],
                fill=color
            )
            
            # 绘制文字
            draw.text((x1 + 5, label_y + 2), label, fill=(255, 255, 255))
        
        return img


class PlantDiseaseGUI:
    """植物病害检测 GUI 类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("🌿 植物病害智能检测系统")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # 设置窗口图标 (如果有)
        # self.root.iconbitmap('icon.ico')
        
        # 初始化检测器
        self.detector = PlantDiseaseDetector(
            r'E:\YOLOv8_Projects\models\yolov8n.pt'
        )
        
        # 摄像头相关
        self.cap = None
        self.is_camera_running = False
        self.camera_thread = None
        
        # 当前图片
        self.current_image = None
        self.current_result = None
        
        # 创建界面
        self.create_widgets()
        
        # 加载模型
        self.load_model_in_background()
    
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = ttk.Label(
            main_frame,
            text="🌿 植物病害智能检测系统",
            font=('Microsoft YaHei', 20, 'bold')
        )
        title_label.pack(pady=10)
        
        # 左右分栏
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 左侧：控制面板
        left_frame = ttk.LabelFrame(paned_window, text="控制面板", padding=10)
        paned_window.add(left_frame, weight=1)
        
        # 右侧：显示区域
        right_frame = ttk.LabelFrame(paned_window, text="检测结果", padding=10)
        paned_window.add(right_frame, weight=3)
        
        # ==================== 左侧控制面板 ====================
        
        # 模型信息
        model_frame = ttk.LabelFrame(left_frame, text="模型信息", padding=5)
        model_frame.pack(fill=tk.X, pady=5)
        
        self.model_status_label = ttk.Label(
            model_frame,
            text="状态: 加载中...",
            foreground='orange'
        )
        self.model_status_label.pack(anchor=tk.W)
        
        ttk.Label(model_frame, text="模型: yolov8n.pt").pack(anchor=tk.W)
        ttk.Label(model_frame, text="类别: 10种病害").pack(anchor=tk.W)
        
        # 图片检测
        image_frame = ttk.LabelFrame(left_frame, text="图片检测", padding=5)
        image_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(
            image_frame,
            text="📁 选择图片",
            command=self.select_image
        ).pack(fill=tk.X, pady=5)
        
        ttk.Button(
            image_frame,
            text="💾 保存结果",
            command=self.save_result
        ).pack(fill=tk.X, pady=5)
        
        # 摄像头检测
        camera_frame = ttk.LabelFrame(left_frame, text="摄像头检测", padding=5)
        camera_frame.pack(fill=tk.X, pady=10)
        
        self.camera_btn = ttk.Button(
            camera_frame,
            text="📷 打开摄像头",
            command=self.toggle_camera
        )
        self.camera_btn.pack(fill=tk.X, pady=5)
        
        # 置信度设置
        conf_frame = ttk.LabelFrame(left_frame, text="检测参数", padding=5)
        conf_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(conf_frame, text="置信度阈值:").pack(anchor=tk.W)
        self.conf_slider = ttk.Scale(
            conf_frame,
            from_=0.1,
            to=0.9,
            orient=tk.HORIZONTAL,
            value=0.25
        )
        self.conf_slider.pack(fill=tk.X)
        self.conf_label = ttk.Label(conf_frame, text="0.25")
        self.conf_label.pack(anchor=tk.W)
        self.conf_slider.bind('<Motion>', self.update_conf_label)
        
        # 检测结果统计
        stats_frame = ttk.LabelFrame(left_frame, text="检测结果", padding=5)
        stats_frame.pack(fill=tk.X, pady=10)
        
        self.stats_text = scrolledtext.ScrolledText(
            stats_frame,
            height=8,
            wrap=tk.WORD
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self.stats_text.insert(tk.END, "等待检测...\n")
        
        # ==================== 右侧显示区域 ====================
        
        # 图片显示
        self.image_label = ttk.Label(right_frame, text="请选择图片或打开摄像头")
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # 状态栏
        self.status_bar = ttk.Label(
            main_frame,
            text="就绪",
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.pack(fill=tk.X, pady=(10, 0))
    
    def load_model_in_background(self):
        """后台加载模型"""
        def load():
            success = self.detector.load_model()
            if success:
                self.model_status_label.config(
                    text="状态: 已加载 ✓",
                    foreground='green'
                )
                self.status_bar.config(text="模型加载成功，可以开始检测")
            else:
                self.model_status_label.config(
                    text="状态: 加载失败 ✗",
                    foreground='red'
                )
                self.status_bar.config(text="模型加载失败，请检查模型文件")
        
        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()
    
    def update_conf_label(self, event=None):
        """更新置信度标签"""
        value = self.conf_slider.get()
        self.conf_label.config(text=f"{value:.2f}")
    
    def select_image(self):
        """选择图片"""
        file_path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.bmp"),
                ("所有文件", "*.*")
            ]
        )
        
        if not file_path:
            return
        
        self.status_bar.config(text=f"正在检测: {os.path.basename(file_path)}")
        
        # 在新线程中检测
        def detect_thread():
            conf_thres = self.conf_slider.get()
            result, error = self.detector.detect(file_path, conf_thres)
            
            if error:
                self.root.after(0, lambda: messagebox.showerror("错误", error))
                return
            
            # 绘制结果
            img_with_boxes = self.detector.draw_results(file_path, result)
            
            # 保存结果
            self.current_image = img_with_boxes
            self.current_result = result
            
            # 显示图片
            self.root.after(0, lambda: self.show_image(img_with_boxes))
            
            # 更新统计
            self.root.after(0, lambda: self.update_stats(result))
            
            self.root.after(
                0,
                lambda: self.status_bar.config(text="检测完成")
            )
        
        thread = threading.Thread(target=detect_thread)
        thread.daemon = True
        thread.start()
    
    def show_image(self, pil_image):
        """显示图片"""
        # 调整图片大小适应窗口
        display_width = 800
        display_height = 600
        
        img_resized = pil_image.copy()
        img_resized.thumbnail((display_width, display_height), Image.Resampling.LANCZOS)
        
        # 转换为Tkinter格式
        photo = ImageTk.PhotoImage(img_resized)
        
        self.image_label.config(image=photo)
        self.image_label.image = photo  # 保持引用
    
    def update_stats(self, result):
        """更新检测结果统计"""
        self.stats_text.delete(1.0, tk.END)
        
        if result is None or len(result.boxes) == 0:
            self.stats_text.insert(tk.END, "未检测到病害\n")
            return
        
        # 统计各类别
        class_counts = {}
        for box in result.boxes:
            cls_id = int(box.cls)
            class_counts[cls_id] = class_counts.get(cls_id, 0) + 1
        
        # 显示结果
        self.stats_text.insert(tk.END, f"检测时间: {time.strftime('%H:%M:%S')}\n")
        self.stats_text.insert(tk.END, f"检测到: {len(result.boxes)} 个目标\n")
        self.stats_text.insert(tk.END, "-" * 30 + "\n")
        
        for cls_id, count in sorted(class_counts.items()):
            name = self.detector.class_names.get(cls_id, f'Class {cls_id}')
            self.stats_text.insert(tk.END, f"{name}: {count} 处\n")
    
    def save_result(self):
        """保存结果"""
        if self.current_image is None:
            messagebox.showwarning("警告", "没有可保存的结果")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="保存结果",
            defaultextension=".jpg",
            filetypes=[("JPEG图片", "*.jpg"), ("PNG图片", "*.png")]
        )
        
        if file_path:
            self.current_image.save(file_path)
            messagebox.showinfo("成功", f"结果已保存: {file_path}")
    
    def toggle_camera(self):
        """切换摄像头状态"""
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
        self.camera_btn.config(text="⏹️ 关闭摄像头")
        
        # 启动检测线程
        self.camera_thread = threading.Thread(target=self.camera_loop)
        self.camera_thread.daemon = True
        self.camera_thread.start()
        
        self.status_bar.config(text="摄像头已启动")
    
    def stop_camera(self):
        """停止摄像头"""
        self.is_camera_running = False
        
        if self.camera_thread:
            self.camera_thread.join(timeout=1)
        
        if self.cap:
            self.cap.release()
            self.cap = None
        
        self.camera_btn.config(text="📷 打开摄像头")
        self.image_label.config(text="请选择图片或打开摄像头")
        self.status_bar.config(text="摄像头已关闭")
    
    def camera_loop(self):
        """摄像头检测循环"""
        while self.is_camera_running and self.cap:
            ret, frame = self.cap.read()
            if not ret:
                break
            
            # 每隔几帧检测一次 (降低CPU占用)
            if int(time.time() * 10) % 3 == 0:
                conf_thres = self.conf_slider.get()
                result, _ = self.detector.detect(frame, conf_thres)
                
                if result:
                    # 绘制结果
                    img_with_boxes = self.detector.draw_results(frame, result)
                    
                    # 转换格式
                    cv_image = cv2.cvtColor(
                        np.array(img_with_boxes),
                        cv2.COLOR_RGB2BGR
                    )
                    
                    # 显示 (在主线程)
                    self.root.after(0, lambda img=cv_image: self.show_cv_image(img))
                    
                    # 更新统计
                    self.root.after(0, lambda r=result: self.update_stats(r))
            else:
                # 只显示原图
                self.root.after(0, lambda f=frame: self.show_cv_image(f))
            
            # 控制帧率
            time.sleep(0.03)  # ~30 FPS
    
    def show_cv_image(self, cv_image):
        """显示OpenCV图片"""
        # 转换颜色空间
        if len(cv_image.shape) == 3:
            cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        
        # 调整大小
        display_width = 800
        display_height = 600
        
        h, w = cv_image.shape[:2]
        scale = min(display_width / w, display_height / h)
        new_w, new_h = int(w * scale), int(h * scale)
        
        resized = cv2.resize(cv_image, (new_w, new_h))
        
        # 转换为PIL
        pil_image = Image.fromarray(resized)
        photo = ImageTk.PhotoImage(pil_image)
        
        self.image_label.config(image=photo)
        self.image_label.image = photo
    
    def on_closing(self):
        """关闭窗口"""
        self.stop_camera()
        self.root.destroy()


def main():
    """主函数"""
    root = tk.Tk()
    
    # 设置DPI感知
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    
    # 设置主题
    style = ttk.Style()
    style.theme_use('clam')
    
    app = PlantDiseaseGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    print("="*60)
    print("植物病害智能检测系统")
    print("="*60)
    print("功能:")
    print("  1. 选择图片进行检测")
    print("  2. 打开摄像头实时检测")
    print("  3. 调整置信度阈值")
    print("  4. 保存检测结果")
    print("="*60)
    
    root.mainloop()


if __name__ == '__main__':
    main()
