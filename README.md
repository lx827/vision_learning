# vision_learning

> 面向 YOLO、OpenCV 与 MVS 的计算机视觉学习和工程实践仓库

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-orange)](https://pytorch.org/)
[![Ultralytics](https://img.shields.io/badge/Ultralytics-8.0%2B-green)](https://github.com/ultralytics/ultralytics)

---

## 目录

- [项目简介](#项目简介)
- [当前功能](#当前功能)
- [快速开始](#快速开始)
- [相机调试台](#相机调试台)
- [项目结构](#项目结构)
- [相机模块边界](#相机模块边界)
- [文档](#文档)
- [示例](#示例)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

`vision_learning` 是一个持续演进的计算机视觉学习与工程实践仓库，规划覆盖 YOLO 目标检测、OpenCV 图像处理和 MVS 相关实践。

当前代码以 YOLOv8 学习成果为基础，已经包含环境配置、训练、验证、测试、评估和模型导出等流程。后续将在保留现有代码可用性的前提下，按主题逐步整理目录并补充 OpenCV 与 MVS 内容。

**学习目标：**
- 掌握 YOLO 模型的训练、验证、评估、导出与部署流程
- 系统练习 OpenCV 图像处理和传统计算机视觉方法
- 积累 MVS 相关开发、设备接入与视觉应用实践
- 沉淀可复用的配置、工具、示例和实验记录

---

## 当前功能

- **一键环境配置**: 自动检测 CUDA、安装依赖、验证环境
- **完整工作流程**: 训练 → 验证 → 测试 → 评估 → 导出
- **数据与标注辅助**: Ultralytics 训练增强、COCO128 下载、YOLO 标注转 X-AnyLabeling JSON
- **可视化分析**: 训练曲线、混淆矩阵、检测结果展示
- **模型导出**: ONNX、TensorRT、OpenVINO 等格式
- **配置驱动**: YAML 配置文件，支持多实验管理
- **模块化设计**: 易于扩展和定制
- **相机采集控制台**: 统一接入 MVS、DroidCam Client 与 OBS DroidCam

---

## 快速开始

### 1. 环境配置

**Windows:**
```bash
# 双击运行
scripts\setup_env.bat
```

**Linux/macOS:**
```bash
# 添加执行权限
chmod +x scripts/setup_env.sh

# 运行安装脚本
./scripts/setup_env.sh
```

### 2. 下载数据集

```bash
python scripts/download_data.py --dataset coco128
```

### 3. 一键运行

```bash
python scripts/quick_start.py
```

### 4. 分步运行

```bash
# 训练
python src/trainer.py --config configs/train.yaml

# 验证
python src/validator.py --config configs/val.yaml

# 测试
python src/tester.py --config configs/test.yaml

# 评估
python src/evaluator.py --config configs/val.yaml
```

---

## 相机调试台

相机来源栏并列提供 **MVS 工业相机**、**DroidCam 客户端**和 **OBS DroidCam**。三种来源共用实时预览、手动拍照、连续自动拍照和录像按钮，OBS 不再占用页面顶部的独立操作区。MVS 模式另外支持曝光、增益、帧率、白平衡和硬件采集 ROI。OBS 安装、使用及验收状态见 [OBS DroidCam 临时采集说明](docs/droidcam/obs_integration.md)。

### 前置条件

使用 MVS 工业相机时：

1. 在 Windows 安装海康机器人 MVS 客户端与 SDK（当前已验证版本：4.8.1）。
2. 确认环境变量 `MVCAM_COMMON_RUNENV` 指向 MVS Development 目录；也可以在页面中手动填写官方 `MvImport` 目录。
3. 关闭正在独占相机的 MVS 官方客户端或其他采集程序。

使用 DroidCam Client 时，让手机端和电脑客户端保持连接并正常显示画面，然后在网页中选择“DroidCam 客户端”和 `DroidCam Video`。程序通过 Windows Media Foundation 和 OpenCV 读取虚拟摄像头输出；手机镜头、曝光、对焦、白平衡等设置仍由 DroidCam 管理。

仓库不会复制或分发官方 SDK 的 Python 文件、DLL、头文件或示例代码；运行时直接从本机 MVS 安装目录加载官方 Python 封装。

### 连接冒烟

```bash
# 枚举配置中的相机、连接、获取一帧并保存测试照片
python scripts/mvs_probe.py --snapshot
```

测试照片默认写入 `data/camera/photos/`，该目录不纳入 Git。

### 启动 Web 调试台

```bash
# 在项目根目录启动本地 Flask 服务
python scripts/camera_web.py
```

服务就绪后会自动打开浏览器并访问 `http://127.0.0.1:8765`。三种来源的连接参数和输出配置保存在 `configs/camera/camera.yaml`；页面中的 IP 只用于选择已经枚举出的 MVS 设备，不会修改相机自身的网络配置。如需只启动服务而不打开浏览器，可运行 `python scripts/camera_web.py --no-browser`。旧命令 `python scripts/mvs_web.py` 仍可作为兼容入口使用。

相机取流、网页预览编码和录像编码分别在独立后台线程中执行。网页每次只请求最新预览帧，处理或显示跟不上时会跳过旧预览帧，不会在浏览器中排队播放过时画面。页面使用一组最大宽高统一控制预览、照片和录像；三类输出都等比例缩小，且不会放大较小的原图或裁剪取景范围。

OBS DroidCam 预览通过选定输入源的 JPEG 截图提供，只用于取景，不参与最终拍照或录像。浏览器在上一帧显示完成后立即请求下一帧，不设置固定限速，也不会并发积压请求；实际刷新率取决于 OBS 截图、HTTP 传输和浏览器解码速度。页面显示的“预览耗时”不包含手机传到 OBS 之前的延迟。OBS 录像目录可在网页中逐次修改，开始录像时临时应用，停止后恢复 OBS 原目录。

“相机采集 ROI”则直接通过 SDK 设置 `Width`、`Height`、`OffsetX` 和 `OffsetY`，只读取传感器上的指定区域，从源头减少传输与处理数据。页面会读取设备实际支持的范围和步长，应用时短暂停流并自动恢复；它与输出缩放互相独立。部分设备（包括当前虚拟相机）重新连接后会恢复全幅，需要连接后再次应用 ROI。

DroidCam Client 不提供 MVS 硬件 ROI，因此该模式只显示“处理区域”：框选结果用于后续算法，预览、照片和录像继续保留完整画面。页面填写的宽度、高度和帧率是向 Windows 虚拟摄像头提出的请求，连接后应以页面显示的实际分辨率和实测帧率为准。

实时画面右侧可以直接拖框选择区域。“相机采集 ROI”模式会自动换算原始像素坐标并对齐设备步长；“处理区域”模式只记录后续算法使用的坐标，预览、照片和录像仍保留完整画面。精确数值输入折叠在同一工具栏中，无需离开实时画面。

相机ROI工具栏同时显示当前采集区域的传感器绝对起点，并提供“恢复完整画面”按钮；在已缩小的ROI上再次框选时，坐标会以当前画面为基准换算回传感器坐标。

录像帧率自动跟随相机当前的 `AcquisitionFrameRate`，无需在输出设置中重复填写。网页关闭或刷新时会主动断开相机；正常停止服务也会释放 SDK 句柄。若进程被强制终止，虚拟相机可能来不及清理，需要在 MVS 客户端中强制重置。

实时画面分别显示相机采集帧率、后端预览编码帧率、浏览器显示帧率和浏览器收到画面时的帧龄。采集帧率连续低于目标值的 90% 时，画面下方会显示持续警告，列出目标值、实际值、补帧数量、可确认或可能的原因以及调整建议。曝光时间、丢包和编码队列可给出明确诊断；带宽、分辨率、像素转换与主机性能会标记为可能原因，避免将推测当作事实。

终端默认不打印成功的预览帧和每秒状态轮询访问日志，避免实时取景时刷屏；连接、参数修改、拍照、录像等操作请求以及 HTTP 错误仍会保留。

---

## 项目结构

```
vision_learning/
├── configs/                    # 配置文件目录
│   ├── train.yaml             # 训练配置
│   ├── val.yaml               # 验证配置
│   ├── test.yaml              # 测试配置
│   ├── export.yaml            # 模型导出配置
│   ├── data/                  # 数据集配置（本地使用，不提交）
│   ├── camera/
│   │   └── camera.yaml        # 三种相机来源的共享控制台配置
│   └── yolo/
│       └── xanylabeling/      # X-AnyLabeling 模型配置
│
├── src/                       # 源代码目录
│   ├── trainer.py             # 训练器
│   ├── validator.py           # 验证器
│   ├── tester.py              # 测试器
│   ├── evaluator.py           # 评估器
│   ├── exporter.py            # 导出器
│   ├── camera_console/        # 共享 Web 页面、采集调度与录像
│   ├── droidcam/              # DroidCam Client 与 OBS DroidCam 适配
│   └── mvs/                   # 海康 MVS SDK 适配
│
├── tools/                     # 工具目录
│   ├── visualization/         # 可视化工具
│   │   ├── curves.py          # 训练曲线
│   │   ├── confusion.py       # 混淆矩阵
│   │   └── detection.py       # 检测结果
│   └── utils/                 # 通用工具
│       ├── env_check.py       # 环境检查
│       ├── logger.py          # 日志管理
│       └── helpers.py         # 辅助函数
│
├── scripts/                   # 脚本目录
│   ├── setup_env.sh           # Linux/macOS 环境配置脚本
│   ├── setup_env.bat          # Windows 环境配置脚本
│   ├── quick_start.py         # 快速开始脚本
│   ├── download_data.py       # 数据集下载脚本
│   ├── yolo_to_xanylabeling.py# YOLO 标注转 X-AnyLabeling JSON
│   ├── mvs_probe.py           # MVS 设备与单帧冒烟检查
│   ├── camera_web.py          # 启动共享相机控制台
│   └── mvs_web.py             # 兼容旧启动命令
│
├── examples/                  # 示例目录
│   ├── train_example.py       # 训练示例
│   ├── val_example.py         # 验证示例
│   ├── test_example.py        # 测试示例
│   └── export_example.py      # 导出示例
│
├── docs/                      # 文档目录
│   ├── README.md              # 文档总索引（分类导航）
│   ├── getting-started/       # 入门上手
│   │   ├── installation.md    #   安装指南
│   │   └── quickstart.md      #   快速开始
│   ├── guides/                # 使用指南
│   │   └── data_preparation.md#   数据准备
│   ├── droidcam/              # DroidCam/OBS 集成说明与设计记录
│   ├── api/                   # 接口参考
│   │   └── api_reference.md   #   API 文档
│   └── theory/                # 理论学习
│       └── yolo_theory.md     #   YOLOv8 理论知识
│
├── tests/                     # 测试目录
│   ├── camera_console/        # 共享相机控制台测试
│   ├── droidcam/              # DroidCam Client 与 OBS 测试
│   ├── mvs/                   # MVS SDK 适配测试
│   └── test_*.py              # YOLO 核心模块与工具测试
│
├── data/                      # 数据目录（gitignore）
├── runs/                      # 运行输出目录（gitignore）
├── weights/                   # 本地模型文件（gitignore）
│   └── yolo/
│       ├── pytorch/           # PyTorch 权重（.pt）
│       └── onnx/              # ONNX 导出模型（.onnx）
│
├── .gitignore                 # Git 忽略文件
├── requirements.txt           # Python 依赖列表
├── requirements-obs.txt       # OBS 控制可选依赖
├── setup.py                   # 包安装配置
├── LICENSE                    # MIT 许可证
└── README.md                  # 项目说明文档
```

模型权重和导出文件体积较大，仅保存在本地 `weights/` 目录，不纳入 Git。仓库中只跟踪可复用的配置、代码和文档。

---

## 相机模块边界

共享控制台、两类 DroidCam 适配与 MVS SDK 适配互为同级模块。新增来源时应在对应适配目录实现，再由控制台统一调度，不能放入另一种硬件适配目录。

```text
src/
├── camera_console/            # 页面、共享配置、采集调度与录像
├── droidcam/                  # DroidCam Client 和 OBS DroidCam
└── mvs/                       # 海康 MVS SDK
```

---

## 文档

详见 [文档中心](docs/README.md) 的按类导航，重点文档如下：

- [安装指南](docs/getting-started/installation.md) - 详细的环境配置说明
- [快速开始](docs/getting-started/quickstart.md) - 5 分钟上手教程
- [数据准备](docs/guides/data_preparation.md) - 数据集格式和准备方法
- [API 文档](docs/api/api_reference.md) - 核心模块使用说明
- [OBS DroidCam 临时采集](docs/droidcam/obs_integration.md) - 手机来源接入与验收记录
- [YOLOv8 理论知识](docs/theory/yolo_theory.md) - 算法原理与公式推导
- [学习路线](plan/plan.md) - 完整的 YOLO 学习路径

---

## 示例

### 训练示例

```python
from src.trainer import YOLOTrainer

# 创建训练器
trainer = YOLOTrainer("configs/train.yaml")

# 开始训练
metrics = trainer.train()

print(f"最佳模型: {metrics['best_model']}")
```

### 验证示例

```python
from src.validator import YOLOValidator

# 创建验证器
validator = YOLOValidator("configs/val.yaml")

# 开始验证
metrics = validator.validate()
validator.print_metrics()
```

### 测试示例

```python
from src.tester import YOLOTester

# 创建测试器
tester = YOLOTester("configs/test.yaml")

# 测试图片
results = tester.test_image("path/to/image.jpg")
```

### 导出示例

```python
from src.exporter import YOLOExporter

# 创建导出器
exporter = YOLOExporter("configs/export.yaml")

# 导出 ONNX
exporter.export_onnx(imgsz=640, half=False, dynamic=True)
```

更多示例请查看 [examples/](examples/) 目录。

---

## 贡献指南

欢迎贡献！请随时提交 Issue 或 Pull Request。

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/AmazingFeature`）
3. 提交更改（`git commit -m 'Add some AmazingFeature'`）
4. 推送到分支（`git push origin feature/AmazingFeature`）
5. 提交 Pull Request

---

## 许可证

本项目采用 MIT 许可证 —— 详见 [LICENSE](LICENSE) 文件

---

## 致谢

- [Ultralytics](https://github.com/ultralytics/ultralytics) 提供了优秀的 YOLO 框架
- [Roboflow](https://roboflow.com) 提供了数据集托管和标注工具
- 所有数据集提供者和开源贡献者

---
