# API 文档

本文档提供核心模块的详细 API 使用说明。

## 目录

- [训练器 (YOLOTrainer)](#训练器-yolotrainer)
- [验证器 (YOLOValidator)](#验证器-yolovalidator)
- [测试器 (YOLOTester)](#测试器-yolotester)
- [评估器 (YOLOEvaluator)](#评估器-yoloevaluator)
- [导出器 (YOLOExporter)](#导出器-yoloexporter)
- [标注转换脚本](#标注转换脚本)
- [可视化工具](#可视化工具)

---

## 训练器 (YOLOTrainer)

### 初始化

```python
from src.trainer import YOLOTrainer

# 使用配置文件
trainer = YOLOTrainer("configs/train.yaml")

# 使用字典配置
config = {
    "model": {"name": "weights/yolo/pytorch/yolov8n.pt"},
    "data": {"name": "coco128.yaml"},
    "train": {"epochs": 50, "batch": 16},
}
trainer = YOLOTrainer(config)
```

### 训练模型

```python
# 基础训练
metrics = trainer.train()

# 断点续训
metrics = trainer.train(resume=True)
```

**返回指标：**
- `best_fitness`: 最佳适应度
- `best_epoch`: 最佳轮数
- `best_model`: 最佳模型路径
- `last_model`: 最后模型路径
- `save_dir`: 结果保存目录

### 导出模型

```python
# 导出 ONNX
export_path = trainer.export(format="onnx", imgsz=640, half=False)

# 导出 TensorRT
export_path = trainer.export(format="engine", imgsz=640, half=True)
```

---

## 验证器 (YOLOValidator)

### 初始化

```python
from src.validator import YOLOValidator

# 使用配置文件
validator = YOLOValidator("configs/val.yaml")

# 使用字典配置
config = {
    "model": {"weights": "weights/yolo/pytorch/yolov8n.pt"},
    "data": {"name": "coco128.yaml"},
    "val": {"batch": 32, "imgsz": 640},
}
validator = YOLOValidator(config)
```

### 验证模型

```python
# 开始验证
metrics = validator.validate()

# 打印指标
validator.print_metrics()
```

**返回指标：**
- `map50`: mAP@0.5
- `map50_95`: mAP@0.5:0.95
- `precision`: 精确率
- `recall`: 召回率
- `per_class_map`: 每个类别的 AP

---

## 测试器 (YOLOTester)

### 初始化

```python
from src.tester import YOLOTester

# 使用配置文件
tester = YOLOTester("configs/test.yaml")

# 使用字典配置
config = {
    "model": {"weights": "weights/yolo/pytorch/yolov8n.pt"},
    "data": {"source": "data/images"},
    "test": {"imgsz": 640, "conf": 0.25},
}
tester = YOLOTester(config)
```

### 测试图片

```python
# 测试单张图片
results = tester.test_image("path/to/image.jpg")

# 测试图片目录
results = tester.test(source="data/images")
```

### 测试视频

```python
# 测试视频
results = tester.test_video("path/to/video.mp4")
```

### 测试摄像头

```python
# 测试摄像头
results = tester.test_camera(camera_id=0)
```

### 获取测试摘要

```python
summary = tester.get_summary()
print(f"处理图片数: {summary['total_images']}")
print(f"检测目标数: {summary['total_detections']}")
```

---

## 评估器 (YOLOEvaluator)

### 初始化

```python
from src.evaluator import YOLOEvaluator

# 使用配置文件
evaluator = YOLOEvaluator("configs/val.yaml")
```

### 评估模型

```python
# 开始评估
report = evaluator.evaluate()

# 打印报告
evaluator.print_report()

# 保存报告
evaluator.save_report("runs/evaluation_report.json")
```

**报告内容：**
- `summary`: 总体指标（mAP、精确率、召回率等）
- `per_class`: 每个类别的 AP
- `curves`: PR 曲线、F1 曲线数据
- `confusion_matrix`: 混淆矩阵

---

## 导出器 (YOLOExporter)

### 初始化

```python
from src.exporter import YOLOExporter

# 使用配置文件
exporter = YOLOExporter("configs/export.yaml")
```

### 导出 ONNX

```python
export_path = exporter.export_onnx(
    imgsz=640,
    half=False,
    dynamic=True,
    simplify=True,
    opset=12,
)
```

### 导出 TensorRT

```python
export_path = exporter.export_tensorrt(
    imgsz=640,
    half=True,
    dynamic=False,
    workspace=4,
)
```

### 导出 OpenVINO

```python
export_path = exporter.export_openvino(
    imgsz=640,
    half=False,
)
```

### 导出所有格式

```python
results = exporter.export_all(
    formats=["onnx", "engine", "openvino"],
    imgsz=640,
    half=True,
)
```

---

## 标注转换脚本

仓库当前提供 YOLO 检测标注到 X-AnyLabeling JSON 的单向转换脚本。类别文件每行一个类别名，行号对应从 0 开始的类别 ID；默认不会覆盖图片目录中已有的 JSON。

```bash
python scripts/yolo_to_xanylabeling.py \
    --images data/custom/train/images \
    --labels data/custom/train/labels \
    --classes data/custom/classes.txt
```

如需覆盖已有 JSON，显式增加 `--overwrite`。仓库目前没有独立的 VOC/COCO 转 YOLO、数据集划分或离线增强 API；训练时的数据增强由 `YOLOTrainer` 根据 `configs/train.yaml` 的 `augment` 配置交给 Ultralytics 执行。

---

## 可视化工具

### 训练曲线 (CurvePlotter)

```python
from tools.visualization.curves import CurvePlotter

# 创建绘制器
plotter = CurvePlotter()

# 绘制训练曲线
plotter.plot_training_curves(
    results_csv="runs/detect/train/exp/results.csv",
    output_dir="runs/curves",
    experiment_name="my_experiment",
)

# 绘制学习率曲线
plotter.plot_learning_rate(
    results_csv="runs/detect/train/exp/results.csv",
    output_dir="runs/curves",
    experiment_name="my_experiment",
)

# 绘制多实验对比
plotter.plot_comparison(
    results_dict={
        "exp1": "runs/detect/train/exp1/results.csv",
        "exp2": "runs/detect/train/exp2/results.csv",
    },
    output_dir="runs/curves",
    metric="metrics/mAP50(B)",
)
```

### 混淆矩阵 (ConfusionMatrixPlotter)

```python
from tools.visualization.confusion import ConfusionMatrixPlotter

# 创建绘制器
plotter = ConfusionMatrixPlotter()

# 绘制混淆矩阵
plotter.plot_confusion_matrix(
    confusion_matrix=cm,
    class_names=["class1", "class2"],
    output_dir="runs/confusion",
    normalize=True,
)
```

### 检测结果 (DetectionVisualizer)

```python
from tools.visualization.detection import DetectionVisualizer

# 创建可视化器
visualizer = DetectionVisualizer()

# 可视化检测结果
visualizer.visualize_results(
    results=results,
    output_dir="runs/visualization",
    class_names=["class1", "class2"],
    max_images=20,
)

# 绘制检测统计图表
visualizer.plot_detection_statistics(
    results=results,
    output_dir="runs/visualization",
    class_names=["class1", "class2"],
)
```

---

## 工具函数

### 环境检查

```python
from tools.utils.env_check import check_environment, print_environment_report

# 检查环境
env_info = check_environment()

# 打印环境报告
print_environment_report(env_info)
```

### 日志管理

```python
from tools.utils.logger import setup_logger, get_logger

# 设置日志
logger = setup_logger(
    name="my_logger",
    level="info",
    log_dir="logs",
)

# 获取日志
logger = get_logger("my_logger")
logger.info("这是一条日志")
```

### 辅助函数

```python
from tools.utils.helpers import (
    get_project_root,
    ensure_dir,
    timer,
    format_time,
    load_yaml,
    save_yaml,
)

# 获取项目根目录
root = get_project_root()

# 确保目录存在
ensure_dir("data/output")

# 计时器
with timer("训练"):
    # 执行训练代码
    pass

# 格式化时间
time_str = format_time(3661)  # "1.02 小时"

# 加载 YAML 配置
config = load_yaml("configs/train.yaml")

# 保存 YAML 配置
save_yaml(config, "configs/train_backup.yaml")
```

---

## 配置文件说明

### 训练配置 (configs/train.yaml)

```yaml
model:
  name: weights/yolo/pytorch/yolov8n.pt  # 模型名称或路径

data:
  name: coco128.yaml        # 数据集配置文件

train:
  epochs: 50                # 训练轮数
  batch: 16                 # 批次大小
  imgsz: 640                # 输入图片尺寸
  lr0: 0.01                 # 初始学习率
  device: 0                 # 训练设备
  workers: 8                # 数据加载线程数
  project: train           # 项目输出目录
  name: exp                 # 实验名称
```

### 验证配置 (configs/val.yaml)

```yaml
model:
  weights: runs/detect/train/exp/weights/best.pt  # 模型权重路径

data:
  name: coco128.yaml        # 数据集配置文件

val:
  batch: 32                 # 批次大小
  imgsz: 640                # 输入图片尺寸
  conf: 0.001               # 置信度阈值
  iou: 0.6                  # NMS IoU 阈值
  device: 0                 # 验证设备
  project: val             # 项目输出目录
  name: exp                 # 实验名称
```

### 测试配置 (configs/test.yaml)

```yaml
model:
  weights: runs/detect/train/exp/weights/best.pt  # 模型权重路径

data:
  source: data/images       # 测试源路径

test:
  imgsz: 640                # 输入图片尺寸
  conf: 0.25                # 置信度阈值
  iou: 0.45                 # NMS IoU 阈值
  device: 0                 # 测试设备
  project: test            # 项目输出目录
  name: exp                 # 实验名称
```

---

## 命令行工具

### 训练

```bash
python src/trainer.py --config configs/train.yaml [--resume]
```

### 验证

```bash
python src/validator.py --config configs/val.yaml [--weights WEIGHTS]
```

### 测试

```bash
python src/tester.py --config configs/test.yaml [--weights WEIGHTS] [--source SOURCE]
```

### 评估

```bash
python src/evaluator.py --config configs/val.yaml [--weights WEIGHTS] [--save SAVE]
```

### 导出

```bash
python src/exporter.py --config configs/export.yaml [--weights WEIGHTS] [--format FORMAT] [--all]
```

### 标注转换

```bash
python scripts/yolo_to_xanylabeling.py --images IMAGES --labels LABELS --classes CLASSES [--overwrite]
```

### 相机控制台

```bash
python scripts/camera_web.py [--config CONFIG] [--no-browser]
```

---

## 下一步

- 查看 [快速开始](../getting-started/quickstart.md) 了解如何快速上手
- 查看 [数据准备](../guides/data_preparation.md) 了解如何准备数据集
- 查看 [学习路线](../../plan/plan.md) 了解完整的学习路径
