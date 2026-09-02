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
- [项目结构](#项目结构)
- [目录演进规划](#目录演进规划)
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
- **数据预处理**: 数据增强、格式转换、数据集划分
- **可视化分析**: 训练曲线、混淆矩阵、检测结果展示
- **模型导出**: ONNX、TensorRT、OpenVINO 等格式
- **配置驱动**: YAML 配置文件，支持多实验管理
- **模块化设计**: 易于扩展和定制

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

## 项目结构

```
vision_learning/
├── configs/                    # 配置文件目录
│   ├── train.yaml             # 训练配置
│   ├── val.yaml               # 验证配置
│   ├── test.yaml              # 测试配置
│   ├── export.yaml            # 模型导出配置
│   ├── data/                  # 数据集配置（本地使用，不提交）
│   └── yolo/
│       └── xanylabeling/      # X-AnyLabeling 模型配置
│
├── src/                       # 源代码目录
│   ├── trainer.py             # 训练器
│   ├── validator.py           # 验证器
│   ├── tester.py              # 测试器
│   ├── evaluator.py           # 评估器
│   └── exporter.py            # 导出器
│
├── tools/                     # 工具目录
│   ├── data/                  # 数据处理工具
│   │   ├── augment.py         # 数据增强
│   │   ├── convert.py         # 格式转换
│   │   └── split.py           # 数据集划分
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
│   └── download_data.py       # 数据集下载脚本
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
│   ├── api/                   # 接口参考
│   │   └── api_reference.md   #   API 文档
│   └── theory/                # 理论学习
│       └── yolo_theory.md     #   YOLOv8 理论知识
│
├── tests/                     # 测试目录
│   ├── test_trainer.py        # 训练器测试
│   ├── test_validator.py      # 验证器测试
│   └── test_tools.py          # 工具测试
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
├── setup.py                   # 包安装配置
├── LICENSE                    # MIT 许可证
└── README.md                  # 项目说明文档
```

模型权重和导出文件体积较大，仅保存在本地 `weights/` 目录，不纳入 Git。仓库中只跟踪可复用的配置、代码和文档。

---

## 目录演进规划

为避免一次性移动代码造成导入路径和现有脚本失效，当前阶段只确定目录边界，不立即重构。后续按功能逐步迁移为：

```text
vision_learning/
├── src/
│   ├── yolo/                  # YOLO 训练、验证、评估、导出与推理
│   ├── opencv/                # OpenCV 图像处理与传统视觉算法
│   ├── mvs/                   # MVS 相关接入、采集与应用实践
│   └── common/                # 跨方向复用的配置、日志和辅助能力
├── configs/
│   ├── yolo/
│   ├── opencv/
│   └── mvs/
├── examples/
│   ├── yolo/
│   ├── opencv/
│   └── mvs/
├── tests/
│   ├── yolo/
│   ├── opencv/
│   └── mvs/
└── docs/
    ├── yolo/
    ├── opencv/
    └── mvs/
```

迁移原则：一次只迁移一个可验证的功能单元；同步更新导入、配置、文档和测试；每次迁移后保持原有使用方式可追踪、变更可回退。

---

## 文档

详见 [文档中心](docs/README.md) 的按类导航，重点文档如下：

- [安装指南](docs/getting-started/installation.md) - 详细的环境配置说明
- [快速开始](docs/getting-started/quickstart.md) - 5 分钟上手教程
- [数据准备](docs/guides/data_preparation.md) - 数据集格式和准备方法
- [API 文档](docs/api/api_reference.md) - 核心模块使用说明
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
