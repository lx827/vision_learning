"""通过 Windows 标准摄像头接口只读采集 DroidCam Client 视频源。"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Callable

import cv2
from cv2_enumerate_cameras import enumerate_cameras

from .config import DroidCamClientConfig
from src.mvs.sdk import FloatFeature, Frame, MvsError


@dataclass(frozen=True)
class StandardCameraDeviceInfo:
    index: int
    transport: str = "MediaFoundation"
    model: str = "Windows 普通摄像头"
    serial: str = ""
    user_name: str = ""
    ip: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "transport": self.transport,
            "model": self.model,
            "serial": self.serial,
            "user_name": self.user_name,
            "ip": self.ip,
        }


class StandardCamera:
    """将 OpenCV ``VideoCapture`` 封装成采集服务所需的只读相机接口。"""

    def __init__(
        self,
        config: DroidCamClientConfig,
        *,
        capture_factory: Callable[..., Any] = cv2.VideoCapture,
    ) -> None:
        self._config = config
        self._capture_factory = capture_factory
        self._capture: Any | None = None
        self._device: StandardCameraDeviceInfo | None = None
        self._frame_number = 0
        self._width = 0
        self._height = 0
        self._fps = 0.0
        self._lock = threading.RLock()

    @staticmethod
    def _backend() -> int:
        return cv2.CAP_MSMF if os.name == "nt" else cv2.CAP_ANY

    @classmethod
    def enumerate_devices(
        cls,
        config: DroidCamClientConfig,
        *,
        capture_factory: Callable[..., Any] = cv2.VideoCapture,
        camera_enumerator: Callable[..., Any] = enumerate_cameras,
    ) -> list[StandardCameraDeviceInfo]:
        del config, capture_factory
        return [
            StandardCameraDeviceInfo(
                index=int(info.index),
                model=str(info.name),
                serial=str(info.index),
                user_name=f"编号 {info.index}",
            )
            for info in camera_enumerator(cls._backend())
        ]

    def open(self) -> StandardCameraDeviceInfo:
        with self._lock:
            if self._capture is not None:
                return self._device or self._make_device()
            capture = self._capture_factory(self._config.device_index, self._backend())
            if not capture.isOpened():
                capture.release()
                raise MvsError(
                    f"无法打开 Windows 摄像头 {self._config.device_index}；"
                    "请确认 DroidCam 正在出画面且没有被其他程序独占"
                )
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.requested_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.requested_height)
            capture.set(cv2.CAP_PROP_FPS, self._config.requested_fps)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, frame = capture.read()
            if not ok or frame is None:
                capture.release()
                raise MvsError(
                    f"Windows 摄像头 {self._config.device_index} 已打开但没有返回画面；"
                    "请检查 DroidCam Client 的虚拟摄像头输出"
                )
            self._capture = capture
            self._height, self._width = frame.shape[:2]
            reported_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            self._fps = reported_fps if reported_fps > 0 else self._config.requested_fps
            self._frame_number = 0
            self._device = self._make_device()
            return self._device

    def _make_device(self) -> StandardCameraDeviceInfo:
        detail = f"{self._width}×{self._height}"
        if self._fps > 0:
            detail += f" / 驱动报告 {self._fps:.1f} FPS"
        return StandardCameraDeviceInfo(
            index=self._config.device_index,
            model=self._config.device_name
            or f"Windows 摄像头 {self._config.device_index}",
            serial=str(self._config.device_index),
            user_name=detail,
        )

    def get_frame(self, timeout_ms: int = 1000) -> Frame | None:
        del timeout_ms  # Media Foundation 的 read() 不提供逐次调用超时参数。
        with self._lock:
            capture = self._capture
            if capture is None:
                raise MvsError("普通摄像头尚未连接")
            ok, image = capture.read()
            if not ok or image is None:
                raise MvsError("DroidCam/普通摄像头画面读取失败")
            self._frame_number += 1
            height, width = image.shape[:2]
            self._width, self._height = width, height
            return Frame(image, self._frame_number, width, height, 0, 0)

    def get_parameters(self) -> dict[str, Any]:
        with self._lock:
            fps = self._fps or self._config.requested_fps
            return {
                "capabilities": {
                    "exposure_mode": False,
                    "exposure_us": False,
                    "gain_mode": False,
                    "gain_db": False,
                    "frame_rate_enabled": False,
                    "frame_rate": False,
                    "white_balance_mode": False,
                    "width": False,
                    "height": False,
                    "offset_x": False,
                    "offset_y": False,
                },
                "frame_rate": FloatFeature(fps, fps, fps).to_dict(),
                "requested_width": self._config.requested_width,
                "requested_height": self._config.requested_height,
                "requested_fps": self._config.requested_fps,
                "controls_external": True,
            }

    def apply_parameters(self, values: dict[str, Any]) -> dict[str, Any]:
        if values:
            raise MvsError("手机镜头、曝光、对焦和白平衡请在 DroidCam 中设置")
        return self.get_parameters()

    def apply_roi(self, values: dict[str, Any]) -> dict[str, Any]:
        del values
        raise MvsError("DroidCam/普通摄像头不支持 MVS 硬件 ROI，请使用处理区域")

    def close(self) -> None:
        with self._lock:
            capture = self._capture
            self._capture = None
            self._device = None
            if capture is not None:
                capture.release()


__all__ = ["StandardCamera", "StandardCameraDeviceInfo"]
