# 使用已训练模型批量预标注扇贝肉图片

## 已准备的文件

- 图片副本：`data/camera_autolabel/`，共 296 张，准备时仅含图片，没有复制 JSON、YOLO 标签或类别文件；原始图片与人工标签保留在 `data/camera/`。
- X-AnyLabeling 模型配置：`configs/xanylabeling/yolov8s_scallop_meat.yaml`。
- ONNX 模型：`weights/yolo/onnx/scallop_meat_yolov8s.onnx`。
- 模型来源：`runs/detect/train/scallop_meat_yolov8s_e100_20260916/weights/best.pt`，类别为 `0 = scallop_meat`。

ONNX 采用 FP32、固定输入 `[1, 3, 640, 640]`、batch 1、opset 12，输出 `[1, 5, 8400]`，不内置 NMS，由 X-AnyLabeling 的 YOLOv8 适配器完成后处理。配置使用软件实际读取的 `conf_threshold`，初始值为 0.25，IoU 为 0.45。模型路径是本机绝对路径，移动仓库后需更新 `model_path`。

本次没有重新训练，也没有在副本目录生成自动标注。296 张图片包含训练/验证用过的 56 张，因此批量预测用于预标注与目视检查，不是独立模型测试。

## 在 X-AnyLabeling 中操作

1. 打开软件，通过 **文件 → 打开目录**（默认快捷键 `Ctrl+U`）选择 `E:/A-codehub/vision_learning/data/camera_autolabel`。
2. 通过 **文件 → 更改输出目录**（默认 `Ctrl+Shift+S`）将标注输出目录也设为上述副本目录；检查自动保存是否开启。
3. 打开 AI/自动标注面板，在模型下拉列表选择 **加载自定义模型**，选取 `configs/xanylabeling/yolov8s_scallop_meat.yaml`。导入的是 YAML，模型路径已由配置指定。
4. 在一张图片上点击 **运行**（默认快捷键 `I`），检查输出是否为 `scallop_meat` 矩形框。
5. 通过 **批量标注**（默认快捷键 `Ctrl+B`）打开批量窗口，选择全部图片并启动，等待完成。快捷键及加载入口参考 [官方用户手册](https://github.com/CVHub520/X-AnyLabeling/blob/main/docs/zh_cn/user_guide.md) 和 [自定义模型说明](https://github.com/CVHub520/X-AnyLabeling/blob/main/docs/zh_cn/custom_model.md)。
6. 在副本目录逐张检查生成的 JSON，纠正漏框、错框、重复框，再考虑导出 YOLO HBB。导出类别文件可使用已有的 `data/camera/photos/classes.txt`。

置信度初始为 0.25；漏框较多时可尝试降低到 0.15～0.20，错框较多时可尝试提高到 0.35～0.50，然后在代表性图片上重新检查。上述阈值是人工检查时的起步范围，尚未通过独立评估优化。

ONNX 已通过结构与本机推理检查；当前项目 Python 环境未安装 `anylabeling` 模块，因此没有直接验证你使用的 X-AnyLabeling 桌面程序加载和批量保存流程。配置依据官方 YOLOv8 适配器编写。
