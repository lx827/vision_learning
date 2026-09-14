"""共享相机控制台的配置模型与 YAML 持久化。"""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from src.droidcam.config import DroidCamClientConfig, ObsDroidCamConfig


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

    photo_dir: str = "data/camera/photos"
    video_dir: str = "data/camera/videos"
    photo_format: str = "jpg"
    jpeg_quality: int = 95
    auto_interval_seconds: float = 5.0
    video_format: str = "mp4"
    video_fps: float = 15.0
    output_max_width: int = 1920
    output_max_height: int = 1080
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
        if self.output_max_width < 2 or self.output_max_height < 2:
            raise ValueError("统一输出最大宽高不能小于 2 像素")
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
class CameraConsoleConfig:
    """相机调试台完整配置。"""

    source_type: str = "mvs"
    camera: CameraConnectionConfig = field(default_factory=CameraConnectionConfig)
    droidcam_client: DroidCamClientConfig = field(default_factory=DroidCamClientConfig)
    obs_droidcam: ObsDroidCamConfig = field(default_factory=ObsDroidCamConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    def validate(self) -> None:
        if self.source_type not in {"mvs", "droidcam_client", "obs_droidcam"}:
            raise ValueError("相机来源仅支持 mvs、droidcam_client 或 obs_droidcam")
        self.camera.validate()
        self.droidcam_client.validate()
        self.obs_droidcam.validate()
        self.capture.validate()
        self.server.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CameraConsoleConfig":
        data = data or {}
        capture_data = dict(data.get("capture") or {})
        # 兼容短期出现过的三套独立尺寸；统一时优先保留照片尺寸。
        for dimension in ("width", "height"):
            output_key = f"output_max_{dimension}"
            independent_keys = [
                f"photo_max_{dimension}",
                f"video_max_{dimension}",
                f"preview_max_{dimension}",
            ]
            if output_key not in capture_data:
                for key in independent_keys:
                    if key in capture_data:
                        capture_data[output_key] = capture_data[key]
                        break
            for key in independent_keys:
                capture_data.pop(key, None)
        source_type = str(data.get("source_type") or "mvs")
        if source_type == "opencv":
            source_type = "droidcam_client"
        droidcam_data = data.get("droidcam_client") or data.get("standard_camera") or {}
        config = cls(
            source_type=source_type,
            camera=CameraConnectionConfig(**(data.get("camera") or {})),
            droidcam_client=DroidCamClientConfig(**droidcam_data),
            obs_droidcam=ObsDroidCamConfig(**(data.get("obs_droidcam") or {})),
            capture=CaptureConfig(**capture_data),
            server=ServerConfig(**(data.get("server") or {})),
        )
        config.validate()
        return config


class CameraConfigStore:
    """以原子替换方式读写调试台 YAML 配置。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> CameraConsoleConfig:
        if not self.path.exists():
            return CameraConsoleConfig()
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if data is not None and not isinstance(data, dict):
            raise ValueError("相机控制台配置文件顶层必须是映射")
        return CameraConsoleConfig.from_dict(data)

    def save(self, config: CameraConsoleConfig) -> None:
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


# 兼容目录拆分前使用的类名。
MvsAppConfig = CameraConsoleConfig
MvsConfigStore = CameraConfigStore

__all__ = [
    "CameraConnectionConfig",
    "CameraConsoleConfig",
    "CameraConfigStore",
    "CaptureConfig",
    "MvsAppConfig",
    "MvsConfigStore",
    "ServerConfig",
]
