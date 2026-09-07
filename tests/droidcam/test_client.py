import cv2
import numpy as np
import pytest
from types import SimpleNamespace

from src.droidcam.config import DroidCamClientConfig
from src.mvs.sdk import MvsError
from src.droidcam.client import StandardCamera


class FakeCapture:
    instances = []

    def __init__(self, index, backend):
        self.index = index
        self.backend = backend
        self.released = False
        self.settings = {}
        self.frame_number = 0
        self.instances.append(self)

    def isOpened(self):
        return self.index == 1

    def read(self):
        if not self.isOpened():
            return False, None
        self.frame_number += 1
        return True, np.full((720, 1280, 3), self.frame_number, dtype=np.uint8)

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return 30.0
        return self.settings.get(prop, 0)

    def set(self, prop, value):
        self.settings[prop] = value
        return True

    def release(self):
        self.released = True


@pytest.fixture(autouse=True)
def clear_fake_captures():
    FakeCapture.instances.clear()


def test_enumeration_returns_windows_camera_names_and_indices():
    config = DroidCamClientConfig()

    devices = StandardCamera.enumerate_devices(
        config,
        camera_enumerator=lambda backend: [
            SimpleNamespace(index=1, name="DroidCam Video")
        ],
    )

    assert [device.index for device in devices] == [1]
    assert devices[0].model == "DroidCam Video"
    assert devices[0].user_name == "编号 1"


def test_open_reads_frames_requests_format_and_releases_capture():
    config = DroidCamClientConfig(
        device_index=1,
        requested_width=1920,
        requested_height=1080,
        requested_fps=30,
    )
    camera = StandardCamera(config, capture_factory=FakeCapture)

    device = camera.open()
    frame = camera.get_frame()
    capture = FakeCapture.instances[-1]
    parameters = camera.get_parameters()
    camera.close()

    assert device.transport == "MediaFoundation"
    assert frame is not None and frame.image.shape == (720, 1280, 3)
    assert capture.settings[cv2.CAP_PROP_FRAME_WIDTH] == 1920
    assert capture.settings[cv2.CAP_PROP_FRAME_HEIGHT] == 1080
    assert capture.settings[cv2.CAP_PROP_FPS] == 30
    assert parameters["controls_external"] is True
    assert capture.released is True


def test_hardware_roi_is_explicitly_rejected():
    camera = StandardCamera(DroidCamClientConfig(), capture_factory=FakeCapture)

    with pytest.raises(MvsError, match="不支持 MVS 硬件 ROI"):
        camera.apply_roi({"width": 100})
