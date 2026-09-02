"""MVS 调试台配置模型与 YAML 持久化。"""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


@dataclass
class CameraConnectionConfig:
    """相机选择和 SDK 定位配置。"""

    ip: str = ""
    serial: str = ""
    sdk_python_path: str = ""
    frame_timeout_ms: int = 1000

    def validate(self) -> None:
        if self.ip:
            ipaddress.ip_address(self.ip)
        if self.frame_timeout_ms < 100 or self.frame_timeout_ms > 30000:
            raise ValueError("取帧超时必须在 100～30000 ms 之间")


@dataclass
class CaptureConfig:
    """照片、自动拍照、预览和录像配置。"""

    photo_dir: str = "data/mvs/photos"
    video_dir: str = "data/mvs/videos"
    photo_format: str = "jpg"
    jpeg_quality: int = 95
    auto_interval_seconds: float = 5.0
    video_format: str = "mp4"
    video_fps: float = 15.0
    preview_quality: int = 80

    def validate(self) -> None:
        if self.photo_format not in {"jpg", "png", "bmp"}:
            raise ValueError("照片格式仅支持 jpg、png、bmp")
        if self.video_format not in {"mp4", "avi"}:
            raise ValueError("视频格式仅支持 mp4、avi")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("JPEG 质量必须在 1～100 之间")
        if self.auto_interval_seconds < 0.2:
            raise ValueError("自动拍照间隔不能小于 0.2 秒")
        if not 0.1 <= self.video_fps <= 240:
            raise ValueError("录像帧率必须在 0.1～240 FPS 之间")
        if not 20 <= self.preview_quality <= 100:
            raise ValueError("预览质量必须在 20～100 之间")
        if not self.photo_dir.strip() or not self.video_dir.strip():
            raise ValueError("照片和视频保存目录不能为空")


@dataclass
class ServerConfig:
    """本地 Web 服务配置。"""

    host: str = "127.0.0.1"
    port: int = 8765

    def validate(self) -> None:
        if not self.host.strip():
            raise ValueError("Web 服务监听地址不能为空")
        if not 1 <= self.port <= 65535:
            raise ValueError("Web 服务端口必须在 1～65535 之间")


@dataclass
class MvsAppConfig:
    """MVS 调试台完整配置。"""

    camera: CameraConnectionConfig = field(default_factory=CameraConnectionConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    def validate(self) -> None:
        self.camera.validate()
        self.capture.validate()
        self.server.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MvsAppConfig":
        data = data or {}
        config = cls(
            camera=CameraConnectionConfig(**(data.get("camera") or {})),
            capture=CaptureConfig(**(data.get("capture") or {})),
            server=ServerConfig(**(data.get("server") or {})),
        )
        config.validate()
        return config


class MvsConfigStore:
    """以原子替换方式读写调试台 YAML 配置。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> MvsAppConfig:
        if not self.path.exists():
            return MvsAppConfig()
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if data is not None and not isinstance(data, dict):
            raise ValueError("MVS 配置文件顶层必须是映射")
        return MvsAppConfig.from_dict(data)

    def save(self, config: MvsAppConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            yaml.safe_dump(
                config.to_dict(), handle, allow_unicode=True, sort_keys=False
            )
            temporary = Path(handle.name)
        temporary.replace(self.path)
