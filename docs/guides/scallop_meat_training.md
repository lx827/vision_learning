# 仿真扇贝肉检测训练

第一版使用本地 COCO 预训练 YOLOv8s，整体微调为 `scallop_meat` 单类别检测器。只做训练前准备，不在准备过程中启动训练。

## 已准备的数据与配置

- 训练配置：`configs/train_scallop_meat.yaml`。
- 数据配置：`configs/data/scallop_meat.yaml`，其中数据根目录为本机绝对路径；移动仓库后需要更新 `path`。
- 预训练权重：`weights/yolo/pytorch/yolov8s.pt`。
- 数据集：`data/scallop_meat/train/{images,labels}` 和 `data/scallop_meat/valid/{images,labels}`。
- 训练集：42 张图片、175 个框；验证集：14 张图片、60 个框。
- 类别：`0 = scallop_meat`。

仅使用已标注且通过导出校验的 56 张图片，240 张未标注图片不参与训练。原始采集和标注文件保留在 `data/camera/`。划分按图片随机进行，种子为 42，具体名单见 `data/scallop_meat/split_manifest.json`。

当前数据全是毛刷背景下的仿真模型，随机划分可能让相近连续画面进入两个集合。验证结果不能直接代表真实扇贝肉、未来传送带场景或运行过程中的累计计数准确率。

## 本机环境检查

准备时检查到 Python 位于 `E:/python/python.exe`，PyTorch 为 `2.10.0+cu126`，Ultralytics 为 `8.4.115`，CUDA 可用，显卡为 RTX 4060 Laptop GPU，显存 8GB。YOLOv8s 权重已能加载，数据配置和训练参数通过本机解析检查。没有执行训练，实际训练显存占用和收敛效果尚未验证。

配置采用最多 100 轮、输入尺寸 640、batch 8、AdamW、初始学习率 0.001、整网微调；最后 10 轮关闭 Mosaic。增强采用较温和的颜色变化、缩放与 Mosaic。这些是第一轮基线设置，不是已通过实验选出的最优参数。

## 手动启动训练

在 **Windows PowerShell** 中，把工作目录切换到 `E:/A-codehub/vision_learning`。下面的命令由你手动执行：它调用本仓库训练器，加载独立配置，在 GPU 0 上启动训练，并将日志、指标和权重写入 `runs/logs/` 及 `train/`。不需要管理员权限；首次运行时 Ultralytics 的 AMP 自检或其他组件可能下载辅助资源，因此应允许网络访问。

```powershell
python src/trainer.py --config configs/train_scallop_meat.yaml
```

以上命令使用终端当前的 Python；如使用其他环境，应确保安装了项目依赖且 CUDA 可用。如果出现显存不足，把本配置的 `train.batch` 从 8 改为 4 后重新运行；若 Windows 数据加载进程报错，可以把 `train.workers` 改为 0。尚未发生这些错误，调整方式仅供遇到对应错误时使用。

实验目录自动命名为 `train/scallop_meat_yolov8s_e100_YYYYMMDD/`；同名目录存在时，Ultralytics 会追加编号，具体以控制台输出为准。预计包括 `weights/best.pt`、`weights/last.pt`、`results.csv` 和训练/验证可视化，训练结束后检查控制台是否正常结束、最佳权重是否存在，以及验证预测是否有漏检或误检。仅凭某一张图片的框数量相等，不能证明目标都检测正确。

准备时，现有训练器传入的 `label_smoothing` 和 `crop_fraction` 被本机 Ultralytics 作为弃用参数接受并移除，会产生警告，不影响本次参数解析检查。训练器现有 4 项单元测试全部通过；检查过程只解析参数和加载权重，没有调用训练、验证或预测。后续累计计数需要在传送带安装后补充实际输送数据，并用已知数量的连续视频验证。
