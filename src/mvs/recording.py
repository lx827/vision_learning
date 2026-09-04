"""Non-blocking and race-free OpenCV video recording."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from .sdk import MvsError


@dataclass(frozen=True)
class _FramePacket:
    frame: np.ndarray
    captured_at: float


@dataclass(frozen=True)
class _StopPacket:
    stopped_at: float


def fit_video_frame(
    frame: np.ndarray, *, max_width: int = 1920, max_height: int = 1080
) -> np.ndarray:
    """Fit a BGR frame inside codec-friendly bounds and keep even dimensions."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise MvsError("录像仅支持 BGR 三通道图像")
    height, width = frame.shape[:2]
    if width < 2 or height < 2:
        raise MvsError("录像图像尺寸无效")
    scale = min(1.0, max_width / width, max_height / height)
    target_width = max(2, int(round(width * scale)) // 2 * 2)
    target_height = max(2, int(round(height * scale)) // 2 * 2)
    if (target_width, target_height) == (width, height):
        return frame
    return cv2.resize(
        frame, (target_width, target_height), interpolation=cv2.INTER_AREA
    )


class VideoRecorder:
    """Own a VideoWriter on one worker thread so capture never waits on encoding."""

    def __init__(
        self,
        *,
        writer_factory: Callable[..., Any] = cv2.VideoWriter,
        queue_size: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._writer_factory = writer_factory
        self._queue_size = queue_size
        self._clock = clock
        self._lock = threading.Lock()
        self._queue: queue.Queue[_FramePacket | _StopPacket] | None = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._error: Exception | None = None
        self._dropped_frames = 0
        self._duplicated_frames = 0
        self._output_size = (0, 0)

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    @property
    def output_size(self) -> tuple[int, int]:
        with self._lock:
            return self._output_size

    @property
    def duplicated_frames(self) -> int:
        with self._lock:
            return self._duplicated_frames

    def start(
        self,
        path: str | Path,
        *,
        video_format: str,
        fps: float,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> None:
        with self._lock:
            if self._running:
                return
            self._queue = queue.Queue(maxsize=self._queue_size)
            self._running = True
            self._error = None
            self._dropped_frames = 0
            self._duplicated_frames = 0
            self._output_size = (0, 0)
            started_at = self._clock()
            self._worker = threading.Thread(
                target=self._run,
                args=(
                    str(path),
                    video_format,
                    float(fps),
                    max_width,
                    max_height,
                    started_at,
                ),
                name="mvs-video-writer",
                daemon=True,
            )
            self._worker.start()

    def submit(self, frame: np.ndarray) -> None:
        with self._lock:
            if self._error is not None:
                raise MvsError(f"录像编码失败：{self._error}")
            if not self._running or self._queue is None:
                return
            target_queue = self._queue
            packet = _FramePacket(frame=frame, captured_at=self._clock())
            try:
                target_queue.put_nowait(packet)
                return
            except queue.Full:
                self._dropped_frames += 1
            try:
                target_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                target_queue.put_nowait(packet)
            except queue.Full:
                self._dropped_frames += 1

    def stop(self, timeout: float = 10.0) -> None:
        stopped_at = self._clock()
        with self._lock:
            was_running = self._running
            self._running = False
            target_queue = self._queue
            worker = self._worker
        if was_running and target_queue is not None:
            latest_packet = None
            while True:
                try:
                    item = target_queue.get_nowait()
                    if isinstance(item, _FramePacket):
                        latest_packet = item
                except queue.Empty:
                    break
            if latest_packet is not None and target_queue.maxsize > 1:
                target_queue.put_nowait(latest_packet)
            target_queue.put_nowait(_StopPacket(stopped_at=stopped_at))
        if worker is not None:
            worker.join(timeout=timeout)
            if worker.is_alive():
                raise MvsError("停止录像超时；编码线程仍在收尾，但相机预览可以继续")
        with self._lock:
            error = self._error
            self._queue = None
            self._worker = None
        if error is not None:
            raise MvsError(f"录像编码失败：{error}") from error

    def _run(
        self,
        path: str,
        video_format: str,
        fps: float,
        max_width: int,
        max_height: int,
        started_at: float,
    ) -> None:
        writer = None
        previous_frame = None
        previous_written = False
        frames_written = 0
        duplicated_frames = 0
        try:
            while True:
                target_queue = self._queue
                if target_queue is None:
                    return
                item = target_queue.get()
                if isinstance(item, _StopPacket):
                    if writer is not None and previous_frame is not None:
                        elapsed = max(0.0, item.stopped_at - started_at)
                        target_frames = max(1, int(round(elapsed * fps)))
                        while frames_written < target_frames:
                            writer.write(previous_frame)
                            frames_written += 1
                            if previous_written:
                                duplicated_frames += 1
                            else:
                                previous_written = True
                        with self._lock:
                            self._duplicated_frames = duplicated_frames
                    return
                frame = fit_video_frame(
                    item.frame, max_width=max_width, max_height=max_height
                )
                if writer is None:
                    height, width = frame.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(
                        *("mp4v" if video_format == "mp4" else "MJPG")
                    )
                    writer = self._writer_factory(path, fourcc, fps, (width, height))
                    if not writer.isOpened():
                        raise MvsError(f"无法创建录像文件：{path}")
                    with self._lock:
                        self._output_size = (width, height)
                    previous_frame = frame
                    previous_written = False
                    continue
                target_frames = max(
                    frames_written,
                    int(round((item.captured_at - started_at) * fps)),
                )
                while frames_written < target_frames:
                    writer.write(previous_frame)
                    frames_written += 1
                    if previous_written:
                        duplicated_frames += 1
                    else:
                        previous_written = True
                with self._lock:
                    self._duplicated_frames = duplicated_frames
                previous_frame = frame
                previous_written = False
        except Exception as exc:
            with self._lock:
                self._error = exc
                self._running = False
        finally:
            if writer is not None:
                writer.release()


__all__ = ["VideoRecorder", "fit_video_frame"]
