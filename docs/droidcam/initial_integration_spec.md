# OBS 临时相机集成初始任务说明

> 本文保留最初的设计输入。当前实现与验收结果以同目录的 `obs_integration.md` 为准；后续用户需求已增加低帧率网页取景预览，并将 DroidCam Client 保留为并列的临时来源。

## 任务目标

在不破坏现有 MVS SDK 相机方案的前提下，把标准 OBS Studio 作为手机临时采集、预览和录像引擎。网页仍然是主要操作界面，Python 后端负责连接 OBS 并执行操作。

## 已确认的决定

- 当前 DroidCam/手机方案的约 14 FPS 问题暂不继续修复，网页现状保持可用即可。
- 不再把独立 DroidCam 电脑客户端作为主要集成目标。
- 手机端仍使用 DroidCam App；电脑端使用标准 OBS Studio 和官方 DroidCam OBS 插件。
- OBS 只作为临时手机方案，正式工业相机仍使用 MVS SDK。
- 不要把 OBS 源码或 `libobs` 嵌入项目；优先把 OBS 作为独立后台进程，通过 obs-websocket 控制。
- 浏览器不能直接暴露 OBS 密码。浏览器调用本项目后端，后端再连接 OBS。

## 目标架构

```text
手机 DroidCam App
        │ USB / Wi-Fi
        ▼
DroidCam OBS 插件
        ▼
OBS Studio（可最小化运行）
        ├── 录像、截图、滤镜
        └── OBS Virtual Camera → 浏览器实时预览

浏览器网页
        ▼ HTTP/WebSocket
本项目 Python 后端
        ▼ obs-websocket（默认 ws://127.0.0.1:4455）
OBS Studio
```

## OBS 通信方式

OBS 28 及以上版本内置 obs-websocket。用户可在 OBS 中打开：

```text
工具 → WebSocket 服务器设置
```

需要确认并记录：

- 服务是否启用
- 监听端口（默认 4455）
- 密码认证是否启用
- OBS 版本和 obs-websocket 版本

通信是基于 TCP 的持久 WebSocket RPC，不是 REST，也不是原始视频 TCP 流。连接后会经历 Hello、Identify、Identified，然后发送请求并接收响应和事件。

推荐后端库：

- `simpleobsws`：适合当前 FastAPI/异步后端。
- `obsws-python`：同步调用更直接。

不要在前端直接保存 OBS 密码。后端应负责连接、认证、重连、超时和错误转换。

## 第一阶段必须实现的功能

先做最小可验证闭环，不要一次性重写现有网页：

1. 增加 OBS 连接状态检查。
2. 后端能查询 OBS 版本、连接状态和当前场景。
3. 后端能查询/选择 DroidCam OBS 视频源。
4. 网页增加“开始录像”和“停止录像”。
5. 网页增加“手动截图”，调用 `SaveSourceScreenshot` 直接保存文件。
6. 网页增加“自动拍照”参数：间隔、总时长、保存目录、文件名前缀。
7. 自动拍照由后端定时调用 `SaveSourceScreenshot`，不要高频调用 `GetSourceScreenshot`。
8. 网页显示录像状态、时长、截图路径和错误信息。
9. 如果可行，再增加 OBS Virtual Camera 选择，让浏览器通过 `getUserMedia()` 直接预览它。

## 接口能力边界

可以通过 obs-websocket 控制：

- 开始、停止、暂停录像
- 查询录像状态、时长和输出文件
- 保存来源截图
- 查询和修改场景、输入源、滤镜、输出尺寸和目录
- 切换虚拟摄像头
- 获取 OBS CPU、内存、渲染 FPS 等状态
- 接收录像开始/停止、场景切换等事件

不能把 obs-websocket 当作连续原始视频帧接口。`GetSourceScreenshot` 只适合偶尔取单张图，不能用来替代 30 FPS 视频流。OBS 的 `activeFps` 是 OBS 渲染 FPS，不等于手机实际产生的独立帧率。

曝光、白平衡、镜头切换等 DroidCam 手机硬件参数不能假定都能通过通用 OBS 接口修改；只有插件明确暴露的输入参数才可远程修改。MVS 相机的曝光、硬件触发、GPIO、工业 ROI 等必须继续走 MVS SDK。

## 预览方案

优先尝试：

```text
OBS Virtual Camera → 浏览器 getUserMedia() → <video>
```

这样预览不需要经过 Python/OpenCV/JPEG/MJPEG 链路。需要说明：虚拟摄像头只能被同一台电脑上的浏览器访问；如果网页在另一台电脑打开，要另行设计 WebRTC 或流媒体方案。

不要为了预览每秒反复请求 Base64 截图，这会增加延迟和 CPU 占用。

## 不要做的事情

- 不要继续围绕 14 FPS 反复修改当前 DroidCam 采集代码。
- 不要同时开启独立 DroidCam Client、OBS DroidCam 源和项目虚拟摄像头读取，避免重复占用和延迟叠加。
- 不要把 Base64 截图循环当作实时视频。
- 不要默认 OBS 的输出 FPS 等于手机真实采集 FPS。
- 不要修改 MVS SDK 主流程或把 OBS 依赖加入正式 MVS 相机路径。
- 不要在没有验证输入源名称、OBS 版本和插件版本前编写固定配置。

## 验证清单

每完成一个阶段都要验证并记录：

- OBS 能否启动并监听 WebSocket 端口。
- 后端能否完成认证、断开和重连。
- 找不到 OBS、密码错误、场景不存在、输入源不存在时，网页是否显示明确错误。
- 手动截图文件是否存在、尺寸和格式是否正确。
- 自动拍照间隔是否符合设置，文件名是否不重复。
- 录像 5 秒后文件时长是否接近 5 秒。
- OBS Virtual Camera 是否能被浏览器选择并显示。
- 关闭 OBS 后项目是否能安全恢复，不残留后台进程。

每次修复 bug 必须向用户说明：根因、触发条件、修复方式和验证结果；未验证的部分必须明确标记。

## 后续正式方向

后续接入真实工业相机时，保留统一的相机适配接口，例如：

```text
MVS Camera Adapter       正式工业相机
OBS/DroidCam Adapter     临时手机相机
```

网页只面向统一的连接、预览、拍照、录像和参数模型；底层分别实现 MVS SDK 或 OBS WebSocket。不要让临时 OBS 方案反向改变 MVS 的硬件采集语义。

## 新窗口开始时的第一步

先只读检查当前项目、现有后端入口、启动脚本和依赖，然后确认：

1. 当前网页的启动方式。
2. 当前相机后端接口位置。
3. 当前是否已有 OpenCV/DroidCam 采集代码。
4. OBS 是否已安装，版本是多少。
5. DroidCam OBS 插件是否已安装。
6. OBS WebSocket 是否启用以及端口/认证状态。

确认完以上内容后，再提出最小改动方案；未经确认不要启动摄像头、修改配置或大规模重构。
