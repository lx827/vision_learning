"""Background inference service for the standalone scallop counting page."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import yaml

from src.scallop_counter import LineCounter, detection_center

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CountingService:
    def __init__(self, camera_provider: Callable[[], Any], config_path: str | Path):
        self._camera_provider = camera_provider
        self._config_path = Path(config_path)
        if not self._config_path.is_absolute():
            self._config_path = PROJECT_ROOT / self._config_path
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest_jpeg: bytes | None = None
        self._sequence = -1
        self._count = 0
        self._reset_generation = 0
        self._detections = 0
        self._fps = 0.0
        self._error = ""
        self._starting = False
        self._config = self._load_defaults()

    def _load_defaults(self) -> dict[str, Any]:
        data = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        model = data.get("model", {})
        tracking = data.get("tracking", {})
        roi = data.get("roi", {})
        line = data.get("count_line", {})
        return {
            "weights": str(model.get("weights", "")),
            "imgsz": int(model.get("imgsz", 960)),
            "conf": float(model.get("conf", 0.10)),
            "iou": float(model.get("iou", 0.45)),
            "device": model.get("device", 0),
            "tracker": str(tracking.get("tracker", "bytetrack.yaml")),
            "min_track_frames": int(tracking.get("min_track_frames", 3)),
            "roi": {
                "x": int(roi.get("x", 0)),
                "y": int(roi.get("y", 0)),
                "width": int(roi.get("width", 1280)),
                "height": int(roi.get("height", 720)),
            },
            "line_start": [int(v) for v in line.get("start", [640, 0])],
            "line_end": [int(v) for v in line.get("end", [640, 720])],
            "direction": str(line.get("direction", "negative_to_positive")),
            "deadband_px": float(line.get("deadband_px", 4)),
        }

    @property
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._thread is not None and self._thread.is_alive(),
                "starting": self._starting,
                "count": self._count,
                "detections": self._detections,
                "fps": round(self._fps, 1),
                "frame_sequence": self._sequence,
                "error": self._error,
                "config": dict(self._config),
            }

    def start(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status
            config = dict(self._config)
            for key in ("weights", "imgsz", "conf", "iou", "device", "tracker", "min_track_frames", "line_start", "line_end", "direction", "deadband_px"):
                if overrides and key in overrides:
                    config[key] = overrides[key]
            if overrides and isinstance(overrides.get("roi"), dict):
                config["roi"] = {**config["roi"], **overrides["roi"]}
            self._validate(config)
            self._config = config
            self._error = ""
            self._starting = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(config,), name="scallop-counting", daemon=True)
            self._thread.start()
            return self.status

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        worker = self._thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=4)
        with self._lock:
            self._thread = None
            self._starting = False
            self._condition.notify_all()
            return self.status

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._count = 0
            self._reset_generation += 1
            self._latest_jpeg = None
            self._condition.notify_all()
            return self.status

    def wait_for_frame(self, after: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        with self._condition:
            self._condition.wait_for(lambda: self._sequence != after or not self.status["active"], timeout)
            return self._sequence, self._latest_jpeg

    @staticmethod
    def _validate(config: dict[str, Any]) -> None:
        weights = Path(str(config["weights"])).expanduser()
        if not weights.is_absolute():
            weights = PROJECT_ROOT / weights
        if not weights.is_file():
            raise ValueError(f"找不到模型权重: {weights}")
        if not 0.01 <= float(config["conf"]) <= 0.99:
            raise ValueError("置信度必须在 0.01 到 0.99 之间")
        if int(config["imgsz"]) < 320:
            raise ValueError("输入尺寸不能小于 320")
        roi = config["roi"]
        if any(int(roi[k]) < 0 for k in ("x", "y")) or any(int(roi[k]) <= 0 for k in ("width", "height")):
            raise ValueError("ROI 参数无效")
        LineCounter(
            (tuple(config["line_start"]), tuple(config["line_end"])),
            direction=str(config["direction"]),
            min_track_frames=int(config["min_track_frames"]),
            deadband_px=float(config["deadband_px"]),
        )

    def _run(self, config: dict[str, Any]) -> None:
        try:
            from ultralytics import YOLO

            weights = Path(str(config["weights"])).expanduser()
            if not weights.is_absolute():
                weights = PROJECT_ROOT / weights
            model = YOLO(str(weights))
            counter = LineCounter(
                (tuple(config["line_start"]), tuple(config["line_end"])),
                direction=str(config["direction"]),
                min_track_frames=int(config["min_track_frames"]),
                deadband_px=float(config["deadband_px"]),
            )
            with self._lock:
                self._starting = False
            camera = self._camera_provider()
            if not camera.status().get("connected"):
                camera.connect()
            times: list[float] = []
            sequence = -1
            reset_generation = -1
            while not self._stop.is_set():
                latest = camera.latest_image(after=sequence)
                if latest is None:
                    continue
                sequence, frame = latest
                with self._lock:
                    if reset_generation != self._reset_generation:
                        # Keep ID history so clearing cannot count the same scallop twice.
                        counter.count = 0
                        reset_generation = self._reset_generation
                roi = config["roi"]
                x, y, width, height = (int(roi[k]) for k in ("x", "y", "width", "height"))
                crop = frame[y : y + height, x : x + width]
                result = model.track(
                    crop,
                    persist=True,
                    tracker=config["tracker"],
                    imgsz=int(config["imgsz"]),
                    conf=float(config["conf"]),
                    iou=float(config["iou"]),
                    device=config["device"],
                    classes=[0],
                    verbose=False,
                )[0]
                boxes = result.boxes
                ids = boxes.id.int().cpu().tolist() if boxes is not None and boxes.id is not None else [None] * (len(boxes) if boxes is not None else 0)
                annotated = frame.copy()
                cv2.rectangle(annotated, (x, y), (x + width, y + height), (48, 190, 220), 2)
                cv2.line(annotated, tuple(config["line_start"]), tuple(config["line_end"]), (0, 80, 255), 3)
                current = 0
                for box, confidence, track_id in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), ids):
                    x1, y1, x2, y2 = [int(value) for value in box]
                    full_box = (x1 + x, y1 + y, x2 + x, y2 + y)
                    center = detection_center(full_box)
                    if track_id is not None:
                        counter.update(int(track_id), center)
                    current += 1
                    color = (35, 220, 80) if track_id not in counter.counted_ids else (0, 190, 255)
                    cv2.rectangle(annotated, (full_box[0], full_box[1]), (full_box[2], full_box[3]), color, 2)
                    label = f"ID {track_id if track_id is not None else '-'}  {float(confidence):.2f}"
                    cv2.putText(annotated, label, (full_box[0], max(22, full_box[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                cv2.rectangle(annotated, (14, 14), (300, 102), (22, 28, 32), -1)
                cv2.putText(annotated, f"Count  {counter.count}", (28, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                cv2.putText(annotated, f"Detect  {current}", (28, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (210, 220, 225), 1)
                ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
                if not ok:
                    continue
                now = time.monotonic()
                times.append(now)
                times = times[-30:]
                fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 else 0.0
                with self._condition:
                    # A reset during inference also invalidates the old overlay.
                    if reset_generation != self._reset_generation:
                        continue
                    self._sequence = sequence
                    self._latest_jpeg = encoded.tobytes()
                    self._count = counter.count
                    self._detections = current
                    self._fps = fps
                    self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                self._error = str(exc)
                self._starting = False
                self._condition.notify_all()
