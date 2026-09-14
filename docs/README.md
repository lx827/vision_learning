# 文档中心

本目录收录 YOLOv8 学习流程和相机采集控制台的文档，按用途分为五类。

## 入门上手 (getting-started)

面向第一次接触本项目、需要把环境跑起来的读者。

- [安装指南](getting-started/installation.md) — 环境要求、一键安装与手动安装、常见问题
- [快速开始](getting-started/quickstart.md) — 5 分钟上手，覆盖训练/验证/测试/评估全流程与 Python API

## 使用指南 (guides)

面向需要准备数据、使用项目工具的读者。

- [数据准备](guides/data_preparation.md) — YOLO 标注格式、目录组织、训练增强、X-AnyLabeling 转换与数据集配置

## 相机采集 (droidcam)

面向使用共享相机控制台接入 DroidCam 与 OBS 的读者。

- [OBS DroidCam 临时采集](droidcam/obs_integration.md) — 手机来源接入、拍照、连续拍照、录像与验收记录
- [OBS 临时相机集成初始任务说明](droidcam/initial_integration_spec.md) — 保留的初始设计输入；当前行为以集成说明为准

## 接口参考 (api)

面向需要查阅各模块具体用法的开发者。

- [API 文档](api/api_reference.md) — 训练器/验证器/测试器/评估器/导出器、数据处理与可视化工具、配置文件说明、命令行用法

## 理论学习 (theory)

面向希望理解 YOLOv8 原理与数学基础的读者。

- [YOLOv8 阶段一理论知识](theory/yolo_theory.md) — 目标检测基础、YOLO 演进、核心架构、损失函数、训练技巧与评估指标

## 文档总览

| 分类 | 目录 | 文档 | 适合场景 |
|------|------|------|----------|
| 入门上手 | getting-started | installation, quickstart | 环境搭建、第一次跑通流程 |
| 使用指南 | guides | data_preparation | 数据集准备、标注与增强 |
| 相机采集 | droidcam | obs_integration, initial_integration_spec | DroidCam/OBS 接入、设计与验收 |
| 接口参考 | api | api_reference | 查阅模块/工具/命令行用法 |
| 理论学习 | theory | yolo_theory | 理解算法原理与公式推导 |

完整的 YOLO 长期学习路径见 [学习路线](../plan/plan.md)。
