# 仿真扇贝肉检测训练 v1

第二版从第一次训练产出的 YOLOv8s 权重继续微调，数据只用 2026-09-24 采集的 camera_v1。只做训练前准备，不在准备过程中启动训练。

## 已准备的数据与配置

- 训练配置：`configs/data/train_scallop_meat_v1.yaml`。
- 数据配置：`configs/data/scallop_meat_v1.yaml`，其中数据根目录为本机绝对路径；移动仓库后需要更新 `path`。
- 预训练权重：`runs/detect/train/scallop_meat_yolov8s_e100_20260916/weights/best.pt`，即第一次用 camera 数据集训练出的最佳权重，类别同为 `0 = scallop_meat`。
- 数据集：`data/scallop_meat_v1/train/{images,labels}` 和 `data/scallop_meat_v1/valid/{images,labels}`。
- 训练集：50 张图片、119 个框；验证集：16 张图片、43 个框。
- 类别：`0 = scallop_meat`。

标注在 `data/camera_v1/` 完成：73 张图片各有一个 YOLO 标签，其中 66 个非空、7 个为空。仅使用非空标签对应的 66 张；空标签图片不参与训练，也不作为负样本加入。划分按图片随机进行，种子为 42，具体名单见 `data/scallop_meat_v1/split_manifest.json`。

本次没有合并第一次 `data/scallop_meat` 的 56 张图片，两次训练的验证结果不可直接横向比较。

`data/scallop_meat_v1/split_manifest.json` 逐张记录了图片与标签的 SHA-256，可用于确认数据集内容未被改动。

## 本机环境检查

准备时检查到 Python 为 3.13.7，PyTorch 为 `2.10.0+cu126`，Ultralytics 为 `8.4.115`，CUDA 可用，显卡为 RTX 4060 Laptop GPU，显存 8GB。

数据集经 Ultralytics 实际扫描，结果为训练集 50 张图片 / 119 个框、验证集 16 张图片 / 43 个框，0 张损坏图片、0 张背景图，与 manifest 一致；66 个标签文件的每一行均为 5 个字段、类别 id 全为 `0`、坐标均在 0–1 之间，且与图片一一配对。数据配置和权重路径均能正常解析，`best.pt` 可加载且类别数为 1。项目 89 项单元测试全部通过。没有执行训练，实际训练显存占用和收敛效果尚未验证。

训练参数沿用第一次的基线：最多 100 轮、输入尺寸 640、batch 8、AdamW、初始学习率 0.001、整网微调，最后 10 轮关闭 Mosaic；增强同样采用较温和的颜色变化、缩放与 Mosaic。注意本次是从已收敛的 `best.pt` 继续微调，初始学习率仍为 0.001，可能偏大、存在把已有权重带偏的风险；如果训练后指标明显不如第一次，优先把 `train.lr0` 降到 0.0001～0.0005 再试。

## 手动启动训练

在 **Windows PowerShell** 中，把工作目录切换到 `E:/A-codehub/vision_learning`。下面的命令由你手动执行：它调用本仓库训练器，加载独立配置，在 GPU 0 上启动训练，并将日志、指标和权重写入 `runs/logs/` 及 `train/`。不需要管理员权限；首次运行时 Ultralytics 的 AMP 自检或其他组件可能下载辅助资源，因此应允许网络访问。

```powershell
python src/trainer.py --config configs/data/train_scallop_meat_v1.yaml
```

实验目录按「数据集_模型_轮数_日期」自动命名，本次为 `train/scallop_meat_v1_best_e100_YYYYMMDD/`（模型名取自权重文件名 `best.pt`）；同名目录存在时，Ultralytics 会追加编号，具体以控制台输出为准。训练结束后检查控制台是否正常结束、`weights/best.pt` 是否存在，以及验证预测是否有漏检或误检。

如果出现显存不足，把本配置的 `train.batch` 从 8 改为 4 后重新运行；若 Windows 数据加载进程报错，可以把 `train.workers` 改为 0。尚未发生这些错误，调整方式仅供遇到对应错误时使用。

## 结果解读的边界

本次训练集和验证集都来自 2026-09-24 同一次连续拍摄（19:16:43–19:17:20）。随机划分会把画面几乎相同的相邻帧同时放进两个集合，因此验证指标偏乐观，不能代表真实扇贝肉、传送带场景或运行过程中的累计计数准确率，也没有独立测试集可交叉验证。如需可信的泛化结论，应补充另一次独立采集作为测试集。
