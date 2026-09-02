import time
from pathlib import Path

import numpy as np
import pytest

from src.mvs.config import MvsAppConfig, MvsConfigStore
from src.mvs.sdk import FloatFeature, Frame, MvsDeviceInfo, MvsError
from src.mvs.service import MvsCameraService


class FakeCamera:
    def __init__(self, sdk_python_path: str = ""):
        self.sdk_python_path = sdk_python_path
        self.connected = False
        self.frame_number = 0
        self.parameters = {
            "capabilities": {"exposure_us": True},
            "exposure_us": FloatFeature(1000.0, 25.0, 20000.0).to_dict(),
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

    def close(self):
        self.connected = False


def make_service(tmp_path: Path) -> MvsCameraService:
    store = MvsConfigStore(tmp_path / "camera.yaml")
    config = MvsAppConfig()
    config.capture.photo_dir = str(tmp_path / "photos")
    config.capture.video_dir = str(tmp_path / "videos")
    store.save(config)
    return MvsCameraService(store, camera_factory=FakeCamera)


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


def test_auto_capture_requires_connection(tmp_path: Path):
    service = make_service(tmp_path)

    with pytest.raises(MvsError, match="请先连接相机"):
        service.start_auto_capture()
