import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.camera_console.config import CameraConfigStore, CameraConsoleConfig
from src.mvs.sdk import FloatFeature, Frame, MvsDeviceInfo, MvsError
from src.camera_console.service import FrameCameraService, _diagnose_frame_rate, _resize_to_fit
from src.droidcam.client import StandardCameraDeviceInfo


class FakeCamera:
    def __init__(self, sdk_python_path: str = ""):
        self.sdk_python_path = sdk_python_path
        self.connected = False
        self.frame_number = 0
        self.parameters = {
            "capabilities": {
                "exposure_us": True,
                "gain_db": True,
                "gain_mode": False,
                "frame_rate": True,
                "frame_rate_enabled": True,
                "white_balance_mode": False,
            },
            "exposure_us": FloatFeature(1000.0, 25.0, 20000.0).to_dict(),
            "gain_db": FloatFeature(1.0, 0.0, 16.0).to_dict(),
            "frame_rate": FloatFeature(7.5, 0.1, 30.0).to_dict(),
            "frame_rate_enabled": True,
        }

    @staticmethod
    def enumerate_devices(sdk_python_path: str = ""):
        return [MvsDeviceInfo(0, "GigE", "FAKE-CAM", "TEST001", "", "192.168.1.20")]

    def open(self, *, ip: str = "", serial: str = ""):
        self.connected = True
        return self.enumerate_devices()[0]

    def get_frame(self, timeout_ms: int = 1000):
        if not self.connected:
            return None
        time.sleep(0.01)
        self.frame_number += 1
        image = np.full((48, 64, 3), (20, 90, 140), dtype=np.uint8)
        return Frame(image, self.frame_number, 64, 48, 0, 0)

    def get_parameters(self):
        return self.parameters

    def apply_parameters(self, values):
        return {**self.parameters, "applied": values}

    def apply_roi(self, values):
        self.parameters = {**self.parameters, "applied_roi": values}
        return self.parameters

    def close(self):
        self.connected = False


def make_service(tmp_path: Path, **kwargs) -> FrameCameraService:
    store = CameraConfigStore(tmp_path / "camera.yaml")
    config = CameraConsoleConfig()
    config.capture.photo_dir = str(tmp_path / "photos")
    config.capture.video_dir = str(tmp_path / "videos")
    store.save(config)
    return FrameCameraService(store, camera_factory=FakeCamera, **kwargs)


def test_connect_preview_snapshot_and_disconnect(tmp_path: Path):
    service = make_service(tmp_path)
    try:
        connected = service.connect()
        sequence, jpeg = service.wait_for_jpeg(0, timeout=1.0)

        assert connected["device"]["model"] == "FAKE-CAM"
        assert sequence > 0
        assert jpeg is not None and jpeg.startswith(b"\xff\xd8")
        snapshot = Path(service.save_snapshot())
        assert snapshot.is_file() and snapshot.stat().st_size > 0
        assert service.get_parameters()["exposure_us"]["value"] == 1000.0
    finally:
        status = service.disconnect()

    assert status["connected"] is False


def test_droidcam_client_source_keeps_processing_pipeline(
    tmp_path: Path,
):
    class FakeStandardCamera:
        def __init__(self, config):
            self.config = config
            self.connected = False
            self.frame_number = 0

        @staticmethod
        def enumerate_devices(config):
            return [
                StandardCameraDeviceInfo(
                    index=config.device_index,
                    model="DroidCam test source",
                    serial=str(config.device_index),
                )
            ]

        def open(self):
            self.connected = True
            return self.enumerate_devices(self.config)[0]

        def get_frame(self, timeout_ms=1000):
            if not self.connected:
                return None
            time.sleep(0.01)
            self.frame_number += 1
            image = np.full((48, 64, 3), 90, dtype=np.uint8)
            return Frame(image, self.frame_number, 64, 48, 0, 0)

        def get_parameters(self):
            return {
                "capabilities": {},
                "frame_rate": FloatFeature(30.0, 30.0, 30.0).to_dict(),
                "controls_external": True,
            }

        def close(self):
            self.connected = False

    store = CameraConfigStore(tmp_path / "camera.yaml")
    config = CameraConsoleConfig(source_type="droidcam_client")
    config.capture.photo_dir = str(tmp_path / "photos")
    config.capture.video_dir = str(tmp_path / "videos")
    store.save(config)
    service = FrameCameraService(
        store,
        standard_camera_factory=FakeStandardCamera,
    )

    assert service.enumerate_devices("droidcam_client")[0]["model"] == "DroidCam test source"
    try:
        connected = service.connect()
        _, jpeg = service.wait_for_jpeg(0, timeout=1.0)
        region = service.set_processing_region(
            {"x": 4, "y": 5, "width": 20, "height": 10}
        )
        snapshot = Path(service.save_snapshot())
        with pytest.raises(MvsError, match="不支持 MVS 硬件 ROI"):
            service.apply_roi({"width": 32, "height": 24})
    finally:
        disconnected = service.disconnect()

    assert connected["source_type"] == "droidcam_client"
    assert jpeg is not None and jpeg.startswith(b"\xff\xd8")
    assert region["width"] == 20
    assert snapshot.name.startswith("camera_")
    assert disconnected["connected"] is False


def test_auto_capture_requires_connection(tmp_path: Path):
    service = make_service(tmp_path)

    with pytest.raises(MvsError, match="请先连接相机"):
        service.start_auto_capture()


def test_output_resize_keeps_aspect_ratio_and_does_not_upscale():
    frame = np.zeros((700, 1400, 3), dtype=np.uint8)

    resized = _resize_to_fit(frame, max_width=1000, max_height=1000)
    untouched = _resize_to_fit(resized, max_width=2000, max_height=2000)

    assert resized.shape == (500, 1000, 3)
    assert untouched is resized


def test_apply_roi_is_forwarded_to_camera(tmp_path: Path):
    service = make_service(tmp_path)
    try:
        service.connect()
        result = service.apply_roi(
            {"width": 32, "height": 24, "offset_x": 8, "offset_y": 4}
        )
    finally:
        service.disconnect()

    assert result["applied_roi"] == {
        "width": 32,
        "height": 24,
        "offset_x": 8,
        "offset_y": 4,
    }


def test_snapshot_uses_shared_output_bounds(tmp_path: Path):
    service = make_service(tmp_path)
    config = service.config.to_dict()
    config["capture"]["output_max_width"] = 32
    config["capture"]["output_max_height"] = 32
    service.update_config(config)
    try:
        service.connect()
        service.wait_for_jpeg(0, timeout=1.0)
        snapshot = Path(service.save_snapshot())
    finally:
        service.disconnect()

    image = cv2.imread(str(snapshot))
    assert image.shape[:2] == (24, 32)


def test_preview_encoding_does_not_block_camera_capture(tmp_path: Path, monkeypatch):
    encode_started = threading.Event()
    allow_encode = threading.Event()
    original_imencode = cv2.imencode

    def blocking_imencode(*args, **kwargs):
        encode_started.set()
        allow_encode.wait(timeout=2.0)
        return original_imencode(*args, **kwargs)

    monkeypatch.setattr("src.camera_console.service.cv2.imencode", blocking_imencode)
    service = make_service(tmp_path)
    try:
        service.connect()
        assert encode_started.wait(timeout=1.0)
        frame_before = service.status()["frame_number"]
        time.sleep(0.08)
        frame_after = service.status()["frame_number"]

        assert frame_after > frame_before
    finally:
        allow_encode.set()
        service.disconnect()


def test_processing_region_keeps_full_frame_and_is_cleared_by_camera_roi(
    tmp_path: Path,
):
    service = make_service(tmp_path)
    try:
        service.connect()
        service.wait_for_jpeg(0, timeout=1.0)
        region = service.set_processing_region(
            {"x": 10, "y": 8, "width": 30, "height": 20}
        )
        before_roi = service.status()
        service.apply_roi({"width": 32, "height": 24, "centered": True})
        after_roi = service.status()
    finally:
        service.disconnect()

    assert region == {
        "x": 10,
        "y": 8,
        "width": 30,
        "height": 20,
        "source_width": 64,
        "source_height": 48,
    }
    assert (before_roi["width"], before_roi["height"]) == (64, 48)
    assert before_roi["processing_region"] == region
    assert after_roi["processing_region"] is None


def test_processing_region_cannot_exceed_current_frame(tmp_path: Path):
    service = make_service(tmp_path)
    try:
        service.connect()
        service.wait_for_jpeg(0, timeout=1.0)
        with pytest.raises(ValueError, match="不能超过"):
            service.set_processing_region({"x": 50, "y": 10, "width": 20, "height": 20})
    finally:
        service.disconnect()


def test_frame_rate_warning_explains_large_gige_frames():
    diagnostic = _diagnose_frame_rate(
        actual_fps=2.23,
        target_fps=15.5,
        sample_count=10,
        width=7008,
        height=7000,
        transport="GigE",
        exposure_us=5000.0,
        lost_packets=0,
        dropped_frames=0,
        duplicated_frames=20,
    )

    assert diagnostic["active"] is True
    assert diagnostic["state"] == "warning"
    assert diagnostic["target_fps"] == 15.5
    assert diagnostic["actual_fps"] == 2.23
    assert diagnostic["duplicated_frames"] == 20
    assert "7008×7000" in diagnostic["reason"]
    assert "GigE 网络带宽" in diagnostic["reason"]


def test_frame_rate_warning_identifies_exposure_limit():
    diagnostic = _diagnose_frame_rate(
        actual_fps=5.0,
        target_fps=20.0,
        sample_count=10,
        width=1920,
        height=1080,
        transport="USB3",
        exposure_us=60000.0,
        lost_packets=0,
        dropped_frames=0,
        duplicated_frames=0,
    )

    assert diagnostic["active"] is True
    assert "超过目标帧周期" in diagnostic["reason"]
    assert "缩短曝光时间" in diagnostic["recommendation"]


def test_frame_rate_diagnostic_clears_when_target_is_met():
    diagnostic = _diagnose_frame_rate(
        actual_fps=14.2,
        target_fps=15.0,
        sample_count=10,
        width=1920,
        height=1080,
        transport="GigE",
        exposure_us=5000.0,
        lost_packets=0,
        dropped_frames=0,
        duplicated_frames=0,
    )

    assert diagnostic["active"] is False
    assert diagnostic["state"] == "ok"


def test_droidcam_warning_places_limit_before_web_preview():
    diagnostic = _diagnose_frame_rate(
        actual_fps=14.2,
        target_fps=30.0,
        sample_count=20,
        width=1920,
        height=1080,
        transport="MediaFoundation",
        exposure_us=0.0,
        lost_packets=0,
        dropped_frames=0,
        duplicated_frames=0,
    )

    assert "限制发生在网页预览之前" in diagnostic["reason"]
    assert "手机端 Target FPS" in diagnostic["recommendation"]
    assert "With Stats" in diagnostic["recommendation"]


def test_unsupported_imaging_parameters_are_not_sent_to_sdk(tmp_path: Path):
    service = make_service(tmp_path)
    try:
        service.connect()
        result = service.apply_parameters(
            {
                "gain_mode": "continuous",
                "gain_db": 2.0,
                "white_balance_mode": "continuous",
            }
        )
    finally:
        service.disconnect()

    assert result["applied"] == {"gain_db": 2.0}


def test_recording_fps_follows_camera_frame_rate(tmp_path: Path):
    writer_created = threading.Event()
    writer_fps = []

    class FakeWriter:
        def __init__(self, path, fourcc, fps, size):
            writer_fps.append(fps)
            writer_created.set()

        def isOpened(self):
            return True

        def write(self, frame):
            pass

        def release(self):
            pass

    service = make_service(tmp_path, video_writer_factory=FakeWriter)
    try:
        service.connect()
        service.wait_for_jpeg(0, timeout=1.0)
        service.start_recording()
        assert writer_created.wait(timeout=1.0)
        service.stop_recording()
    finally:
        service.disconnect()

    assert writer_fps == [7.5]


def test_device_enumeration_is_serialized(tmp_path: Path):
    class ConcurrentEnumerationCamera(FakeCamera):
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        @staticmethod
        def enumerate_devices(sdk_python_path: str = ""):
            with ConcurrentEnumerationCamera.lock:
                ConcurrentEnumerationCamera.active += 1
                ConcurrentEnumerationCamera.maximum_active = max(
                    ConcurrentEnumerationCamera.maximum_active,
                    ConcurrentEnumerationCamera.active,
                )
            time.sleep(0.05)
            with ConcurrentEnumerationCamera.lock:
                ConcurrentEnumerationCamera.active -= 1
            return FakeCamera.enumerate_devices(sdk_python_path)

    store = CameraConfigStore(tmp_path / "camera.yaml")
    store.save(CameraConsoleConfig())
    service = FrameCameraService(store, camera_factory=ConcurrentEnumerationCamera)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service.enumerate_devices(), range(2)))

    assert [result[0]["model"] for result in results] == ["FAKE-CAM", "FAKE-CAM"]
    assert ConcurrentEnumerationCamera.maximum_active == 1


def test_video_encoding_does_not_block_capture_or_snapshot(tmp_path: Path):
    write_started = threading.Event()
    allow_write = threading.Event()

    class BlockingWriter:
        def isOpened(self):
            return True

        def write(self, frame):
            write_started.set()
            allow_write.wait(timeout=2.0)

        def release(self):
            pass

    service = make_service(
        tmp_path,
        video_writer_factory=lambda *args: BlockingWriter(),
    )
    try:
        service.connect()
        service.wait_for_jpeg(0, timeout=1.0)
        service.start_recording()
        assert write_started.wait(timeout=1.0)

        frame_before = service.status()["frame_number"]
        time.sleep(0.08)
        frame_after = service.status()["frame_number"]
        snapshot = Path(service.save_snapshot())

        assert frame_after > frame_before
        assert snapshot.is_file()
    finally:
        allow_write.set()
        service.stop_recording()
        service.disconnect()
