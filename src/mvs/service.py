"""MVS 相机采集会话：预览、拍照、定时拍照与录像。"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from .config import MvsAppConfig, MvsConfigStore
from .sdk import Frame, MvsCamera, MvsDeviceInfo, MvsError


class MvsCameraService:
    """串行管理单台 MVS 相机，并向 Web 层提供线程安全操作。"""

    def __init__(
        self,
        config_store: MvsConfigStore,
        *,
        camera_factory: Callable[[str], MvsCamera] = MvsCamera,
    ) -> None:
        self._config_store = config_store
        self._config = config_store.load()
        self._camera_factory = camera_factory
        self._camera: MvsCamera | None = None
        self._device: MvsDeviceInfo | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._frame_condition = threading.Condition(self._lock)
        self._operation_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_sequence = 0
        self._latest_frame_number = 0
        self._latest_size = (0, 0)
        self._lost_packets = 0
        self._frame_times: deque[float] = deque(maxlen=60)
        self._connected = False
        self._streaming = False
        self._last_error = ""
        self._last_photo = ""
        self._auto_capture = False
        self._next_auto_capture = 0.0
        self._recording = False
        self._recording_path = ""
        self._video_writer: cv2.VideoWriter | None = None

    @property
    def config(self) -> MvsAppConfig:
        with self._lock:
            return MvsAppConfig.from_dict(self._config.to_dict())

    def update_config(self, data: dict[str, Any]) -> dict[str, Any]:
        config = MvsAppConfig.from_dict(data)
        with self._operation_lock:
            with self._lock:
                if self._connected:
                    current_camera = self._config.camera
                    if config.camera != current_camera:
                        raise MvsError(
                            "相机已连接；修改 IP、序列号、SDK 路径或超时前请先断开"
                        )
                self._config_store.save(config)
                self._config = config
        return config.to_dict()

    def enumerate_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._connected and self._device is not None:
                return [self._device.to_dict()]
            sdk_path = self._config.camera.sdk_python_path
        return [device.to_dict() for device in MvsCamera.enumerate_devices(sdk_path)]

    def connect(self) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                if self._connected:
                    return self.status()
                config = self._config
            camera = self._camera_factory(config.camera.sdk_python_path)
            try:
                device = camera.open(ip=config.camera.ip, serial=config.camera.serial)
            except Exception:
                camera.close()
                raise
            with self._lock:
                self._camera = camera
                self._device = device
                self._connected = True
                self._streaming = True
                self._last_error = ""
                self._stop_event.clear()
                self._worker = threading.Thread(
                    target=self._capture_loop, name="mvs-capture", daemon=True
                )
                self._worker.start()
        return self.status()

    def disconnect(self) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                self._auto_capture = False
                self._recording = False
                self._stop_event.set()
                worker = self._worker
                camera = self._camera
            if worker is not None and worker.is_alive():
                worker.join(
                    timeout=max(2.0, self._config.camera.frame_timeout_ms / 1000 + 1.0)
                )
            self._release_video_writer()
            if camera is not None:
                camera.close()
            with self._lock:
                self._camera = None
                self._device = None
                self._worker = None
                self._connected = False
                self._streaming = False
                self._latest_frame = None
                self._latest_jpeg = None
                self._latest_frame_number = 0
                self._latest_size = (0, 0)
                self._lost_packets = 0
                self._frame_times.clear()
                self._frame_condition.notify_all()
        return self.status()

    def get_parameters(self) -> dict[str, Any]:
        camera = self._require_camera()
        return camera.get_parameters()

    def apply_parameters(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "exposure_mode",
            "exposure_us",
            "gain_mode",
            "gain_db",
            "frame_rate_enabled",
            "frame_rate",
            "white_balance_mode",
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"未知相机参数：{', '.join(unknown)}")
        camera = self._require_camera()
        return camera.apply_parameters(values)

    def save_snapshot(self) -> str:
        with self._lock:
            if self._latest_frame is None:
                raise MvsError("尚未收到相机画面，无法拍照")
            frame = self._latest_frame.copy()
            config = self._config.capture
        path = self._save_photo(frame, config.photo_format, config.jpeg_quality)
        with self._lock:
            self._last_photo = str(path)
        return str(path)

    def start_auto_capture(
        self, interval_seconds: float | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if not self._connected:
                raise MvsError("请先连接相机")
            interval = (
                self._config.capture.auto_interval_seconds
                if interval_seconds is None
                else float(interval_seconds)
            )
            if interval < 0.2:
                raise ValueError("自动拍照间隔不能小于 0.2 秒")
            self._auto_capture = True
            self._next_auto_capture = time.monotonic()
            return self.status()

    def stop_auto_capture(self) -> dict[str, Any]:
        with self._lock:
            self._auto_capture = False
            return self.status()

    def start_recording(self) -> str:
        with self._lock:
            if not self._connected or self._latest_frame is None:
                raise MvsError("请先连接相机并等待实时画面")
            if self._recording:
                return self._recording_path
            config = self._config.capture
            directory = Path(config.video_dir)
            directory.mkdir(parents=True, exist_ok=True)
            suffix = config.video_format
            path = (
                directory / f"mvs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{suffix}"
            )
            self._recording_path = str(path)
            self._recording = True
            self._video_writer = None
            return str(path)

    def stop_recording(self) -> str:
        with self._lock:
            path = self._recording_path
            self._recording = False
        self._release_video_writer()
        return path

    def wait_for_jpeg(
        self, sequence: int, timeout: float = 2.0
    ) -> tuple[int, bytes | None]:
        with self._frame_condition:
            self._frame_condition.wait_for(
                lambda: self._latest_sequence != sequence or not self._connected,
                timeout=timeout,
            )
            return self._latest_sequence, self._latest_jpeg

    def status(self) -> dict[str, Any]:
        with self._lock:
            fps = 0.0
            if len(self._frame_times) >= 2:
                elapsed = self._frame_times[-1] - self._frame_times[0]
                if elapsed > 0:
                    fps = (len(self._frame_times) - 1) / elapsed
            width, height = self._latest_size
            return {
                "connected": self._connected,
                "streaming": self._streaming,
                "auto_capture": self._auto_capture,
                "recording": self._recording,
                "recording_path": self._recording_path,
                "last_photo": self._last_photo,
                "last_error": self._last_error,
                "fps": round(fps, 2),
                "frame_number": self._latest_frame_number,
                "width": width,
                "height": height,
                "lost_packets": self._lost_packets,
                "device": self._device.to_dict() if self._device else None,
            }

    def close(self) -> None:
        self.disconnect()

    def _capture_loop(self) -> None:
        camera = self._camera
        if camera is None:
            return
        try:
            while not self._stop_event.is_set():
                frame = camera.get_frame(self._config.camera.frame_timeout_ms)
                if frame is None:
                    continue
                self._publish_frame(frame)
                self._process_automatic_capture(frame.image)
                self._process_recording(frame.image)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._streaming = False
                self._frame_condition.notify_all()
        finally:
            self._release_video_writer()

    def _publish_frame(self, frame: Frame) -> None:
        quality = self._config.capture.preview_quality
        ok, encoded = cv2.imencode(
            ".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        if not ok:
            raise MvsError("实时预览 JPEG 编码失败")
        now = time.monotonic()
        with self._frame_condition:
            self._latest_frame = frame.image
            self._latest_jpeg = encoded.tobytes()
            self._latest_sequence += 1
            self._latest_frame_number = frame.number
            self._latest_size = (frame.width, frame.height)
            self._lost_packets = frame.lost_packets
            self._frame_times.append(now)
            self._frame_condition.notify_all()

    def _process_automatic_capture(self, frame: np.ndarray) -> None:
        with self._lock:
            if not self._auto_capture or time.monotonic() < self._next_auto_capture:
                return
            config = self._config.capture
            self._next_auto_capture = time.monotonic() + config.auto_interval_seconds
        try:
            path = self._save_photo(frame, config.photo_format, config.jpeg_quality)
            with self._lock:
                self._last_photo = str(path)
        except Exception as exc:
            with self._lock:
                self._last_error = f"自动拍照失败：{exc}"
                self._auto_capture = False

    def _process_recording(self, frame: np.ndarray) -> None:
        with self._lock:
            if not self._recording:
                return
            writer = self._video_writer
            path = self._recording_path
            config = self._config.capture
        if writer is None:
            height, width = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(
                *("mp4v" if config.video_format == "mp4" else "MJPG")
            )
            writer = cv2.VideoWriter(path, fourcc, config.video_fps, (width, height))
            if not writer.isOpened():
                with self._lock:
                    self._recording = False
                raise MvsError(f"无法创建录像文件：{path}")
            with self._lock:
                self._video_writer = writer
        writer.write(frame)

    def _save_photo(self, frame: np.ndarray, image_format: str, quality: int) -> Path:
        directory = Path(self._config.capture.photo_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = (
            directory
            / f"mvs_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{image_format}"
        )
        params = [cv2.IMWRITE_JPEG_QUALITY, quality] if image_format == "jpg" else []
        ok, encoded = cv2.imencode(f".{image_format}", frame, params)
        if not ok:
            raise MvsError(f"{image_format.upper()} 图片编码失败")
        path.write_bytes(encoded.tobytes())
        return path

    def _release_video_writer(self) -> None:
        with self._lock:
            writer = self._video_writer
            self._video_writer = None
        if writer is not None:
            writer.release()

    def _require_camera(self) -> MvsCamera:
        with self._lock:
            if not self._connected or self._camera is None:
                raise MvsError("请先连接相机")
            return self._camera


__all__ = ["MvsCameraService"]
