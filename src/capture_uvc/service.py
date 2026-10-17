"""Capture/UVC 网页会话；原生采集/落盘与可丢帧的预览分离。"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
from uuid import uuid4

import cv2

from .sdk import CaptureCore, CaptureError, CapturedFrame, PROJECT_ROOT, decode_frame


class CaptureUvcService:
    def __init__(self, config_provider: Callable, *, core_factory=CaptureCore):
        self._config_provider = config_provider
        self._core_factory = core_factory
        self._core = None
        self._library_path = None
        self._camera = None
        self._device = None
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._snapshot_lock = threading.Lock()
        self._snapshots_inflight = 0
        self._stop = threading.Event()
        self._auto_stop = threading.Event()
        self._worker = None
        self._auto_worker = None
        self._connected = False
        self._disconnecting = False
        self._reset_preview()
        self._last_photo = ""
        self._error = ""
        self._recording = False
        self._recording_path = ""
        self._recording_started = 0.0
        self._recording_result = {}
        self._recording_size = []
        self._auto_capture = False

    def _reset_preview(self):
        self._frame = None
        self._jpeg = None
        self._preview_sequence = -1
        self._observed_at = 0
        self._preview_size = (0, 0)
        self._preview_times = deque(maxlen=60)
        self._preview_skipped = 0

    def _library(self):
        path = self._config_provider().capture_uvc.library_path
        if self._core is None or path != self._library_path:
            self._core = self._core_factory(path)
            self._library_path = path
        return self._core

    def enumerate_devices(self, source_type=None):
        with self._lock:
            return self._library().devices()

    def formats(self, device_id: str):
        with self._lock:
            if self._connected:
                if device_id != self._device["device_id"]:
                    raise CaptureError("请先断开当前相机，再查询其他设备格式")
                return self._camera.formats()
            if not device_id:
                raise CaptureError("请先选择 Capture/UVC 设备")
            camera = self._library().open(device_id)
            try:
                return camera.formats()
            finally:
                camera.close()

    def connect(self):
        with self._lock:
            if self._disconnecting:
                raise CaptureError("Capture/UVC 正在断开，请稍后重连")
            if self._connected:
                return self.status()
            settings = self._config_provider().capture_uvc
            if not settings.device_id:
                raise CaptureError("请先刷新并选择 Capture/UVC 设备")
            core = self._library()
            device = next(
                (d for d in core.devices() if d["device_id"] == settings.device_id),
                None,
            )
            if device is None:
                raise CaptureError("所选 Capture/UVC 设备已移除，请刷新设备列表")
            camera = core.open(settings.device_id)
            try:
                camera.start(settings.format_index)
                deadline = time.monotonic() + 4
                frame = None
                while time.monotonic() < deadline:
                    frame = camera.latest_frame()
                    if frame is not None:
                        break
                    time.sleep(0.02)
                if frame is None:
                    raise CaptureError(
                        "Capture/UVC 相机启动后未返回首帧；请确认 capture.exe 已停止采集"
                    )
            except Exception:
                camera.close()
                raise
            self._camera, self._device = camera, device
            self._reset_preview()
            self._frame = frame
            self._error = ""
            self._connected = True
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._preview_loop, name="capture-uvc-preview", daemon=True
            )
            self._worker.start()
            return self.status()

    def disconnect(self):
        # 先撤销可操作状态，等待在途快照结束，再与取帧串行释放句柄。
        errors = []
        with self._lock:
            self._disconnecting = True
            self._connected = False
            self._stop.set()
            self._auto_stop.set()
            self._auto_capture = False
            if not self._condition.wait_for(
                lambda: self._snapshots_inflight == 0, timeout=8
            ):
                self._error = "Capture 快照尚未完成，暂未释放相机；请稍后再次断开"
                raise CaptureError(self._error)
            if self._camera:
                if self._recording:
                    try:
                        self._stop_recording()
                    except Exception as exc:
                        errors.append(str(exc))
                try:
                    self._camera.close()
                except Exception as exc:
                    errors.append(str(exc))
                self._camera = None
            self._recording = False
            self._jpeg = None
            self._condition.notify_all()
            workers = (self._worker, self._auto_worker)
        for worker in workers:
            if worker and worker is not threading.current_thread():
                worker.join(timeout=8)
                if worker.is_alive():
                    errors.append("Capture 后台线程未能及时退出")
        with self._lock:
            self._disconnecting = False
        if errors:
            self._error = "；".join(errors)
            raise CaptureError(self._error)
        return self.status()

    def close(self):
        self.disconnect()

    def _require_camera(self):
        if not self._connected or self._camera is None:
            raise CaptureError("请先连接 Capture/UVC 相机")
        if self._error:
            raise CaptureError(self._error + "；请断开并重新连接")
        return self._camera

    def status(self):
        with self._lock:
            stats = self._camera.stats() if self._camera else None
            frame = self._frame
            now = time.monotonic()
            preview_fps = (
                (len(self._preview_times) - 1)
                / (self._preview_times[-1] - self._preview_times[0])
                if len(self._preview_times) > 1
                else 0
            )
            size = [frame.width, frame.height] if frame else [0, 0]
            return {
                "source_type": "capture_uvc",
                "connected": self._connected,
                "streaming": self._connected and not self._error,
                "device": self._device,
                "width": size[0],
                "height": size[1],
                "preview_width": self._preview_size[0],
                "preview_height": self._preview_size[1],
                "capture_fps": stats.measured_fps if stats else 0,
                "preview_fps": (
                    preview_fps if self._connected and not self._error else 0
                ),
                "frame_number": stats.frames_delivered if stats else 0,
                "preview_skipped_frames": self._preview_skipped,
                "preview_frame_age_ms": (
                    max(0, time.time() * 1000 - self._observed_at)
                    if self._observed_at
                    else 0
                ),
                "lost_packets": None,
                "fps_diagnostic": None,
                "processing_region": None,
                "last_photo": self._last_photo,
                "last_error": self._error,
                "auto_capture": self._auto_capture,
                "recording": self._recording,
                "recording_path": self._recording_path,
                "recording_seconds": (
                    round(now - self._recording_started, 1) if self._recording else 0
                ),
                "recording_size": self._recording_size,
                # 内核按设备时间戳录制；不把目标 FPS 或未知丢帧数冒充实测值。
                "recording_fps": None,
                "recording_dropped_frames": None,
                "recording_duplicated_frames": None,
                "recording_result": self._recording_result,
            }

    def _preview_loop(self):
        last_sequence = -1
        last_change = time.monotonic()
        try:
            while not self._stop.is_set():
                with self._lock:
                    if not self._connected:
                        break
                    frame = self._camera.latest_frame(after=last_sequence)
                    config = self._config_provider().capture
                if frame is None or frame.sequence == last_sequence:
                    if time.monotonic() - last_change > 5:
                        raise CaptureError(
                            "Capture/UVC 连续 5 秒没有新帧，请检查设备连接"
                        )
                    self._stop.wait(0.005)
                    continue
                observed_at = int(time.time() * 1000)
                last_change = time.monotonic()
                scale = min(
                    1,
                    config.output_max_width / frame.width,
                    config.output_max_height / frame.height,
                )
                if frame.pixel_format == 0 and scale == 1:
                    jpeg, size = frame.data, (frame.width, frame.height)
                else:
                    image = decode_frame(frame)
                    if scale < 1:
                        image = cv2.resize(
                            image,
                            (
                                max(1, round(frame.width * scale)),
                                max(1, round(frame.height * scale)),
                            ),
                            interpolation=cv2.INTER_AREA,
                        )
                    ok, encoded = cv2.imencode(
                        ".jpg",
                        image,
                        [cv2.IMWRITE_JPEG_QUALITY, config.preview_quality],
                    )
                    if not ok:
                        raise CaptureError("Capture/UVC 预览编码失败")
                    jpeg, size = encoded.tobytes(), (image.shape[1], image.shape[0])
                with self._condition:
                    if not self._connected:
                        break
                    if last_sequence >= 0:
                        self._preview_skipped += max(
                            0, frame.sequence - last_sequence - 1
                        )
                    self._frame = frame
                    self._jpeg, self._preview_sequence = jpeg, frame.sequence
                    self._observed_at, self._preview_size = observed_at, size
                    self._preview_times.append(time.monotonic())
                    self._condition.notify_all()
                last_sequence = frame.sequence
                self._stop.wait(0.005)
        except Exception as exc:
            with self._condition:
                self._error = str(exc)
                self._auto_stop.set()
                self._auto_capture = False
                # 停止并收尾原生录像，避免无新帧时仍显示“录像正常”。
                if self._recording:
                    try:
                        self._stop_recording()
                    except Exception as stop_error:
                        self._error += f"；录像收尾失败：{stop_error}"
                self._jpeg = None
                self._condition.notify_all()

    def wait_for_preview(self, after: int, timeout=2.0):
        with self._condition:
            self._condition.wait_for(
                lambda: self._preview_sequence != after
                or not self._connected
                or self._error,
                timeout,
            )
            if self._error:
                raise CaptureError(self._error)
            if not self._connected:
                return after, None, 0
            return self._preview_sequence, self._jpeg, self._observed_at

    def wait_for_jpeg(self, after, timeout=2.0):
        try:
            sequence, jpeg, _ = self.wait_for_preview(after, timeout)
            return sequence, jpeg
        except CaptureError:
            return after, None

    def get_parameters(self):
        return {"capabilities": {}, "controls_external": True}

    def apply_parameters(self, payload):
        raise CaptureError(
            "Capture/UVC 成像参数请在 capture.exe 中设置；本网页当前提供格式选择与采集控制"
        )

    def apply_roi(self, payload):
        raise CaptureError("Capture/UVC 不提供 MVS 硬件 ROI")

    def set_processing_region(self, payload):
        raise CaptureError("Capture/UVC 当前不提供处理区域框选")

    def clear_processing_region(self):
        return None

    @staticmethod
    def _output_path(directory: str, prefix: str, extension: str):
        path = Path(directory).expanduser()
        path = path if path.is_absolute() else PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return (
            path.resolve()
            / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:6]}.{extension}"
        )

    def save_snapshot(self):
        # 判稳拍照会等待多帧。只串行快照请求，不阻塞预览取帧和状态查询。
        with self._snapshot_lock:
            with self._lock:
                camera = self._require_camera()
                config = self._config_provider().capture
                frame = self._frame
                path = self._output_path(config.photo_dir, "uvc", "jpg")
                self._snapshots_inflight += 1
            try:
                if frame.pixel_format == 0:
                    camera.snapshot(path)
                else:
                    # cap_snapshot 对非 MJPEG 的契约是原始字节，不能直接改名成 JPG。
                    with TemporaryDirectory(
                        prefix=".uvc-snapshot-", dir=path.parent
                    ) as temporary:
                        raw = Path(temporary) / "frame.raw"
                        camera.snapshot(raw)
                        pixels = decode_frame(
                            CapturedFrame(
                                0,
                                0,
                                frame.width,
                                frame.height,
                                frame.pixel_format,
                                raw.read_bytes(),
                            )
                        )
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            pixels,
                            [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality],
                        )
                        if not ok:
                            raise CaptureError("Capture/UVC 快照 JPEG 编码失败")
                        path.write_bytes(encoded.tobytes())
                with self._lock:
                    self._last_photo = str(path)
                return str(path)
            finally:
                with self._condition:
                    self._snapshots_inflight -= 1
                    self._condition.notify_all()

    def start_auto_capture(self, interval_seconds=None):
        with self._lock:
            self._require_camera()
            interval = float(
                interval_seconds
                if interval_seconds is not None
                else self._config_provider().capture.auto_interval_seconds
            )
            if not 0.2 <= interval <= 86400:
                raise ValueError("自动拍照间隔须在 0.2～86400 秒之间")
            if self._auto_capture:
                return self.status()
            if self._auto_worker and self._auto_worker.is_alive():
                raise CaptureError("上一次自动拍照尚未停止，请稍后再试")
            self._auto_stop.clear()
            self._auto_capture = True
            self._auto_worker = threading.Thread(
                target=self._auto_loop,
                args=(interval,),
                name="capture-uvc-auto",
                daemon=True,
            )
            self._auto_worker.start()
            return self.status()

    def _auto_loop(self, interval):
        try:
            while not self._auto_stop.is_set():
                started = time.monotonic()
                self.save_snapshot()
                # 太慢时跳过错过的时点，避免连续补拍。
                elapsed = time.monotonic() - started
                delay = interval - elapsed % interval
                if self._auto_stop.wait(delay):
                    break
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._auto_capture = False

    def stop_auto_capture(self):
        self._auto_stop.set()
        worker = self._auto_worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=8)
            if worker.is_alive():
                raise CaptureError("自动拍照尚未停止，请稍后再试")
        with self._lock:
            self._auto_capture = False
            return self.status()

    def start_recording(self):
        with self._lock:
            camera = self._require_camera()
            if self._recording:
                raise CaptureError("Capture/UVC 已在录像")
            config = self._config_provider().capture
            mjpeg = config.video_format == "avi"
            if mjpeg and self._frame.pixel_format != 0:
                raise CaptureError(
                    "MJPEG/AVI 直通录像需要 MJPEG 采集格式；请选择 MP4 或断开后切换格式"
                )
            path = self._output_path(config.video_dir, "uvc", "avi" if mjpeg else "mp4")
            camera.start_recording(path, mjpeg=mjpeg)
            self._recording = True
            self._recording_size = [self._frame.width, self._frame.height]
            self._recording_path, self._recording_started = str(path), time.monotonic()
            self._recording_result = {}
            return str(path)

    def _stop_recording(self):
        try:
            result = self._camera.stop_recording()
        except Exception as exc:
            self._error = f"Capture/UVC 录像收尾失败：{exc}"
            raise
        finally:
            self._recording = False
        self._recording_result = result
        if result["last_path"]:
            self._recording_path = result["last_path"]
        return self._recording_path

    def stop_recording(self):
        with self._lock:
            if not self._recording:
                return self._recording_path
            return self._stop_recording()
