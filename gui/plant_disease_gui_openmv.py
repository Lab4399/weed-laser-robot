#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
植物病害检测 GUI 程序 - OpenMV集成版
功能：
  1. 图片选择识别
  2. USB摄像头实时检测
  3. OpenMV串口实时检测（核心）
  4. 结果可视化（框+标签+建议）

使用方法：
  python plant_disease_gui_openmv.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import cv2
import numpy as np
import threading
import serial
import serial.tools.list_ports
import struct
import time
import os
import sys

# 添加YOLOv8路径
sys.path.append(r'E:\YOLOv8_Projects\src')

# 尝试导入YOLO
try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    print("⚠️ 警告: ultralytics未安装，OpenMV模式将仅显示图像")


# ==================== 植物病害建议数据库 ====================
DISEASE_ADVICE = {
    'tomato_early_blight': {
        'name': '番茄早疫病',
        'advice': '建议喷洒代森锰锌或百菌清药剂，每7-10天一次，连续2-3次。注意通风透光，降低湿度。',
        'severity': '中等'
    },
    'tomato_late_blight': {
        'name': '番茄晚疫病',
        'advice': '建议立即喷洒甲霜灵或霜脲氰，严重时需清除病株。保持植株干燥，避免夜间浇水。',
        'severity': '严重'
    },
    'tomato_leaf_mold': {
        'name': '番茄叶霉病',
        'advice': '建议喷洒多菌灵或甲基托布津，加强通风，控制湿度在70%以下。',
        'severity': '中等'
    },
    'tomato_septoria': {
        'name': '番茄斑点病',
        'advice': '建议喷洒代森锰锌或百菌清，及时摘除病叶，避免雨水飞溅。',
        'severity': '轻微'
    },
    'tomato_yellow_virus': {
        'name': '番茄黄化病毒',
        'advice': '病毒病无特效药，建议移除病株，防止蚜虫传播，使用抗病毒品种。',
        'severity': '严重'
    },
    'strawberry_leaf_scorch': {
        'name': '草莓叶枯病',
        'advice': '建议喷洒苯醚甲环唑或嘧菌酯，清除病残体，保持植株间距。',
        'severity': '中等'
    },
    'squash_powdery_mildew': {
        'name': '南瓜白粉病',
        'advice': '建议喷洒三唑酮或醚菌酯，增加光照，降低湿度。',
        'severity': '中等'
    },
    'healthy': {
        'name': '健康叶片',
        'advice': '植株健康，继续保持良好管理。',
        'severity': '健康'
    }
}


class PlantDiseaseGUI:
    """植物病害检测GUI - 支持OpenMV"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("🌿 植物病害智能检测系统 (OpenMV集成版)")
        self.root.geometry("1400x900")
        
        # 初始化变量
        self.model = None
        self.cap = None
        self.is_running = False
        self.current_mode = None
        
        # OpenMV相关
        self.ser = None
        self.openmv_thread = None
        self.stop_openmv = False
        self.frame_buffer = b''
        self.expected_len = None
        self.frame_count = 0
        
        # 加载模型
        self.init_model()
        
        # 创建界面
        self.create_ui()
        
        print("="*60)
        print("植物病害检测系统已启动")
        print("="*60)
    
    def init_model(self):
        """初始化检测模型"""
        if not ULTRALYTICS_AVAILABLE:
            self.status_text = "ultralytics未安装，OpenMV模式仅显示图像"
            return
        
        # 尝试加载模型
        model_paths = [
            r'E:\PlantDiseaseProject\models\best.pt',
            r'E:\YOLOv8_Projects\models\yolov8n.pt',
        ]
        
        for path in model_paths:
            if os.path.exists(path):
                try:
                    self.model = YOLO(path)
                    self.status_text = f"模型已加载: {os.path.basename(path)}"
                    print(f"✓ 模型加载成功: {path}")
                    return
                except Exception as e:
                    print(f"✗ 加载失败: {e}")
        
        self.status_text = "未找到模型文件"
        print("⚠ 未找到模型，OpenMV模式将仅显示图像")
    
    def create_ui(self):
        """创建用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = ttk.Label(main_frame, 
                               text="🌿 植物病害智能检测系统", 
                               font=('Microsoft YaHei', 20, 'bold'))
        title_label.pack(pady=10)
        
        # 状态栏
        self.status_label = ttk.Label(main_frame, 
                                     text=f"状态: {self.status_text}", 
                                     font=('Microsoft YaHei', 10))
        self.status_label.pack(pady=5)
        
        # 左右分栏
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # 左侧面板 - 控制区
        left_frame = ttk.LabelFrame(paned, text="控制面板", padding="10")
        paned.add(left_frame, weight=1)
        
        # 右侧面板 - 显示区
        right = ttk.Frame(paned)
        paned.add(right_frame, weight=3)
        
        # ===== 左侧面板内容 =====
        
        # 模式选择
        mode_frame = ttk.LabelFrame(left_frame, text="检测模式", padding="5")
        mode_frame.pack(fill=tk.X, pady=5)
        
        # 图片检测
        ttk.Button(mode_frame, text="📁 选择图片检测", 
                  command=self.select_image).pack(fill=tk.X, pady=2)
        
        # USB摄像头
        ttk.Button(mode_frame, text="📷 开启USB摄像头", 
                  command=self.start_usb_camera).pack(fill=tk.X, pady=2)
        
        # OpenMV模式（核心功能）
        openmv_frame = ttk.LabelFrame(left_frame, text="🎥 OpenMV模式", padding="5")
        openmv_frame.pack(fill=tk.X, pady=10)
        
        # 串口选择
        ttk.Label(openmv_frame, text="串口号:").pack(anchor=tk.W)
        self.port_var = tk.StringVar(value="自动检测")
        self.port_combo = ttk.Combobox(openmv_frame, textvariable=self.port_var, 
                                      values=["自动检测"], state="readonly")
        self.port_combo.pack(fill=tk.X, pady=2)
        self.refresh_ports()
        
        ttk.Button(openmv_frame, text="🔄 刷新串口", 
                  command=self.refresh_ports).pack(fill=tk.X, pady=2)
        
        ttk.Button(openmv_frame, text="▶️ 启动OpenMV检测", 
                  command=self.start_openmv, 
                  style='Accent.TButton').pack(fill=tk.X, pady=5)
        
        # 停止按钮
        ttk.Button(left_frame, text="⏹️ 停止检测", 
                  command=self.stop_detection).pack(fill=tk.X, pady=10)
        
        # 参数设置
        param_frame = ttk.LabelFrame(left_frame, text="检测参数", padding="5")
        param_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(param_frame, text="置信度阈值:").pack(anchor=tk.W)
        self.conf_var = tk.DoubleVar(value=0.25)
        conf_scale = ttk.Scale(param_frame, from_=0.1, to=0.9, 
                              variable=self.conf_var, orient=tk.HORIZONTAL,
                              command=lambda e: self.conf_label.config(text=f"{self.conf_var.get():.2f}"))
        conf_scale.pack(fill=tk.X)
        self.conf_label = ttk.Label(param_frame, text="0.25")
        self.conf_label.pack(anchor=tk.W)
        
        # ===== 右侧面板内容 =====
        
        # 图像显示区
        display_frame = ttk.LabelFrame(right_frame, text="检测结果", padding="5")
        display_frame.pack(fill=tk.BOTH, expand=True)
        
        self.image_label = ttk.Label(display_frame, 
                                    text="请选择检测模式或图片",
                                    background='black',
                                    foreground='white',
                                    font=('Microsoft YaHei', 14))
        self.image_label.pack(fill=tk.BOTH, expand=True)
        
        # 结果信息区
        info_frame = ttk.LabelFrame(right_frame, text="检测详情", padding="5")
        info_frame.pack(fill=tk.X, pady=5)
        
        self.info_text = scrolledtext.ScrolledText(info_frame, height=8, wrap=tk.WORD,
                                                   font=('Microsoft YaHei', 10))
        self.info_text.pack(fill=tk.BOTH, expand=True)
        self.info_text.insert(tk.END, "等待检测...\n")
        
        # 帮助按钮
        ttk.Button(left_frame, text="❓ 使用帮助", 
                  command=self.show_help).pack(fill=tk.X, pady=5)
    
    def refresh_ports(self):
        """刷新可用串口列表"""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ["自动检测"] + ports
        if ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("自动检测")
        print(f"可用串口: {ports}")
    
    def select_image(self):
        """选择图片检测"""
        if not self.model:
            messagebox.showwarning("警告", "模型未加载，无法进行检测")
            return
        
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp"), ("所有文件", "*.*")]
        )
        if not path:
            return
        
        self.stop_detection()
        self.current_mode = 'image'
        
        # 在新线程中处理
        threading.Thread(target=self.process_image, args=(path,), daemon=True).start()
    
    def process_image(self, path):
        """处理图片"""
        try:
            img = cv2.imread(path)
            if img is None:
                self.root.after(0, lambda: messagebox.showerror("错误", "无法读取图片"))
                return
            
            results = self.model(img, conf=self.conf_var.get(), verbose=False)[0]
            annotated = results.plot()
            
            self.root.after(0, lambda: self.show_image(annotated))
            self.root.after(0, lambda: self.update_info(results))
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
    
    def start_usb_camera(self):
        """启动USB摄像头"""
        if not self.model:
            messagebox.showwarning("警告", "模型未加载")
            return
        
        self.stop_detection()
        self.current_mode = 'usb_camera'
        self.is_running = True
        
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            messagebox.showerror("错误", "无法打开摄像头")
            self.is_running = False
            return
        
        threading.Thread(target=self.usb_camera_loop, daemon=True).start()
    
    def usb_camera_loop(self):
        """USB摄像头循环"""
        frame_time = time.time()
        
        while self.is_running and self.current_mode == 'usb_camera':
            ret, frame = self.cap.read()
            if not ret:
                break
            
            # 检测
            results = self.model(frame, conf=self.conf_var.get(), verbose=False)[0]
            annotated = results.plot()
            
            # 计算FPS
            current_time = time.time()
            fps = 1 / (current_time - frame_time) if frame_time else 0
            frame_time = current_time
            
            cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            self.root.after(0, lambda img=annotated: self.show_image(img))
            self.root.after(0, lambda r=results: self.update_info(r))
            
            time.sleep(0.03)  # ~30fps
    
    def start_openmv(self):
        """启动OpenMV模式"""
        self.stop_detection()
        self.current_mode = 'openmv'
        self.is_running = True
        self.stop_openmv = False
        
        # 确定串口
        port = self.port_var.get()
        if port == "自动检测":
            ports = [p.device for p in serial.tools.list_ports.comports()]
            if not ports:
                messagebox.showerror("错误", "未找到可用串口")
                self.is_running = False
                return
            port = ports[0]
        
        print(f"连接OpenMV串口: {port}")
        
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.5)
            time.sleep(2)  # 等待连接稳定
            print("✓ 串口连接成功")
        except Exception as e:
            messagebox.showerror("错误", f"无法打开串口: {e}")
            self.is_running = False
            return
        
        # 启动接收线程
        self.openmv_thread = threading.Thread(target=self.openmv_loop, daemon=True)
        self.openmv_thread.start()
        
        self.info_text.delete(1.0, tk.END)
        self.info_text.insert(tk.END, f"OpenMV模式已启动\n串口: {port}\n等待接收图像...\n")
    
    def openmv_loop(self):
        """OpenMV接收循环 - 核心协议实现"""
        buffer = b''
        expected_len = None
        
        while self.is_running and not self.stop_openmv:
            try:
                # 读取4字节长度（小端序）
                if expected_len is None:
                    if len(buffer) < 4:
                        data = self.ser.read(4 - len(buffer))
                        if data:
                            buffer += data
                        continue
                    
                    expected_len = struct.unpack('<I', buffer[:4])[0]
                    buffer = buffer[4:]
                    
                    # 安全检查
                    if expected_len > 500000:  # 最大500KB
                        print(f"警告: 图像过大 ({expected_len} bytes)，重置")
                        buffer = b''
                        expected_len = None
                        continue
                
                # 读取图像数据
                if len(buffer) < expected_len:
                    data = self.ser.read(expected_len - len(buffer))
                    if data:
                        buffer += data
                    continue
                
                # 获取完整图像数据
                jpeg_data = buffer[:expected_len]
                buffer = buffer[expected_len:]
                expected_len = None
                
                # 解码JPEG
                img_array = np.frombuffer(jpeg_data, dtype=np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                
                if img is None:
                    continue
                
                self.frame_count += 1
                
                # 检测（如果有模型）
                if self.model:
                    results = self.model(img, conf=self.conf_var.get(), verbose=False)[0]
                    annotated = results.plot()
                    
                    self.root.after(0, lambda i=annotated: self.show_image(i))
                    self.root.after(0, lambda r=results: self.update_info(r))
                else:
                    # 仅显示图像
                    self.root.after(0, lambda i=img: self.show_image(i))
                    self.root.after(0, lambda: self.info_text.delete(1.0, tk.END) or 
                                              self.info_text.insert(tk.END, f"接收到图像 #{self.frame_count}\n(模型未加载，仅显示图像)"))
                
            except Exception as e:
                print(f"OpenMV接收错误: {e}")
                time.sleep(0.1)
    
    def show_image(self, cv_img):
        """显示图像"""
        if len(cv_img.shape) == 3:
            cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        
        # 调整大小
        h, w = cv_img.shape[:2]
        max_size = 800
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            cv_img = cv2.resize(cv_img, (int(w*scale), int(h*scale)))
        
        pil_img = Image.fromarray(cv_img)
        photo = ImageTk.PhotoImage(pil_img)
        
        self.image_label.config(image=photo)
        self.image_label.image = photo
    
    def update_info(self, results):
        """更新检测信息"""
        self.info_text.delete(1.0, tk.END)
        
        boxes = results.boxes
        if len(boxes) == 0:
            self.info_text.insert(tk.END, "未检测到目标\n")
            return
        
        self.info_text.insert(tk.END, f"检测到 {len(boxes)} 个目标:\n")
        self.info_text.insert(tk.END, "="*50 + "\n")
        
        for i, box in enumerate(boxes):
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            name = results.names.get(cls_id, f'Class {cls_id}')
            
            self.info_text.insert(tk.END, f"[{i+1}] {name}\n")
            self.info_text.insert(tk.END, f"    置信度: {conf:.3f}\n")
            
            # 查找建议
            for key, info in DISEASE_ADVICE.items():
                if info['name'] == name or key in name.lower():
                    self.info_text.insert(tk.END, f"    严重程度: {info['severity']}\n")
                    self.info_text.insert(tk.END, f"    建议: {info['advice']}\n")
                    break
            
            self.info_text.insert(tk.END, "-"*50 + "\n")
    
    def stop_detection(self):
        """停止检测"""
        self.is_running = False
        self.stop_openmv = True
        
        if self.cap:
            self.cap.release()
            self.cap = None
        
        if self.ser:
            self.ser.close()
            self.ser = None
        
        self.current_mode = None
        self.image_label.config(text="检测已停止", image='')
        print("检测已停止")
    
    def show_help(self):
        """显示帮助"""
        help_text = """使用说明：

【图片检测】
1. 点击"选择图片检测"
2. 选择本地图片文件
3. 查看检测结果和建议

【USB摄像头】
1. 确保摄像头已连接
2. 点击"开启USB摄像头"
3. 实时查看检测结果

【OpenMV模式】（核心功能）
1. 将OpenMV摄像头通过USB连接到电脑
2. 确保已烧录main.py到OpenMV
3. 在串口号选择正确的COM端口
4. 点击"启动OpenMV检测"
5. 等待连接并开始接收图像

【串口通信协议】
- 波特率: 115200
- 数据格式: 
  [0-3]: 4字节图像长度（小端序）
  [4-7]: 4字节帧计数
  [8...]: JPEG图像数据

【注意事项】
- 首次使用需要训练并加载模型(best.pt)
- OpenMV模式帧率约 2-5 fps
- 可通过调整置信度阈值控制检测灵敏度
        """
        messagebox.showinfo("使用帮助", help_text)


def main():
    root = tk.Tk()
    app = PlantDiseaseGUI(root)
    
    # 设置关闭事件
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_detection(), root.destroy()))
    
    root.mainloop()


if __name__ == '__main__':
    main()
