"""两种 DroidCam 临时相机方案的独立配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DroidCamClientConfig:
    """Windows DroidCam Client 虚拟摄像头配置。"""

    device_index: int = 0
    device_name: str = ""
    requested_width: int = 1280
    requested_height: int = 720
    requested_fps: float = 30.0

    def validate(self) -> None:
        if self.device_index < 0:
            raise ValueError("DroidCam 客户端摄像头编号不能小于 0")
        if self.requested_width < 2 or self.requested_height < 2:
            raise ValueError("DroidCam 客户端请求宽高不能小于 2 像素")
        if not 0.1 <= self.requested_fps <= 240:
            raise ValueError("DroidCam 客户端请求帧率必须在 0.1～240 FPS 之间")


@dataclass
class ObsDroidCamConfig:
    """OBS 中的 DroidCam 输入源选择。"""

    source_name: str = ""
    photo_prefix: str = "phone"

    def validate(self) -> None:
        if len(self.source_name) > 256:
            raise ValueError("OBS DroidCam 来源名称过长")
        if not self.photo_prefix.strip() or len(self.photo_prefix) > 64:
            raise ValueError("OBS DroidCam 照片前缀必须为 1～64 个字符")


# 兼容旧导入；新代码使用能表达来源语义的名称。
StandardCameraConfig = DroidCamClientConfig

__all__ = ["DroidCamClientConfig", "ObsDroidCamConfig", "StandardCameraConfig"]
