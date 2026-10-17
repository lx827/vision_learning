"""不依赖硬件的原生采集契约与网页路由回归测试。"""

import ctypes as ct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.camera_console.config import CameraConfigStore, CameraConsoleConfig
from src.camera_console.service import FrameCameraService
from src.camera_console.web import create_app
from src.capture_uvc.sdk import (
    CaptureCamera,
    CaptureCore,
    CaptureError,
    CapturedFrame,
    Frame,
    DeviceInfo,
    Format,
    PropMeta,
    PropOption,
    RecordConfig,
    RecordResult,
    Stats,
    decode_frame,
)
from src.capture_uvc.service import CaptureUvcService


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("后台状态未及时达到预期")


class FakeCamera:
    def __init__(self):
        self.closed = False
        self.sequence = 0
        self.read_error = False
        self.record_calls = []
        self.snapshots = []
        self.recording = False
        self.pixel_format = 0
        self.jpeg = cv2.imencode(".jpg", np.full((12, 16, 3), 80, np.uint8))[
            1
        ].tobytes()

    def formats(self):
        return [
            {
                "index": 0,
                "name": "MJPEG",
                "width": 16,
                "height": 12,
                "fps": 60,
                "pixel_format": 0,
            }
        ]

    def start(self, index):
        self.format_index = index

    def properties(self):
        return [
            {
                "id": 8,
                "name": "white_balance_auto",
                "type": 1,
                "minimum": 0,
                "maximum": 1,
                "step": 1,
                "default": 0,
                "value": getattr(self, "wb_auto", 1),
                "is_auto": False,
                "flags": 0,
                "unit": 0,
                "options": [],
            },
            {
                "id": 9,
                "name": "white_balance_kelvin",
                "type": 0,
                "minimum": 2800,
                "maximum": 6500,
                "step": 10,
                "default": 4600,
                "value": getattr(self, "wb_kelvin", 4600),
                "is_auto": bool(getattr(self, "wb_auto", 1)),
                "flags": 0,
                "unit": 2,
                "options": [],
            },
            {
                "id": 11,
                "name": "exposure_auto",
                "type": 2,
                "minimum": 0,
                "maximum": 3,
                "step": 1,
                "default": 1,
                "value": getattr(self, "exposure_mode", 1),
                "is_auto": False,
                "flags": 0,
                "unit": 0,
                "options": [
                    {"value": 0, "name": "manual"},
                    {"value": 1, "name": "auto"},
                ],
            },
        ]

    def set_property(self, property_id, value, *, boolean=False):
        setattr(
            self,
            {8: "wb_auto", 9: "wb_kelvin", 11: "exposure_mode"}[property_id],
            value,
        )

    def latest_frame(self, after=None):
        assert not self.closed, "禁止在关闭后取帧"
        if self.read_error:
            raise CaptureError("模拟拔出相机")
        self.sequence += 1
        data = self.jpeg if self.pixel_format == 0 else bytes([80, 40, 20]) * 16 * 12
        return CapturedFrame(
            self.sequence, self.sequence * 166667, 16, 12, self.pixel_format, data
        )

    def stats(self):
        return SimpleNamespace(measured_fps=60, frames_delivered=self.sequence)

    def snapshot(self, path):
        assert not self.closed
        path.write_bytes(
            self.jpeg if self.pixel_format == 0 else bytes([80, 40, 20]) * 16 * 12
        )
        self.snapshots.append(path)

    def start_recording(self, path, *, mjpeg):
        self.record_calls.append((path, mjpeg))
        self.recording = True

    def stop_recording(self):
        self.recording = False
        return {
            "last_path": str(self.record_calls[-1][0]),
            "encoder": "passthrough",
            "frames_written": 42,
        }

    def close(self):
        self.closed = True
        self.recording = False


class FakeCore:
    def __init__(self, path):
        self.cameras = []

    def devices(self):
        return [
            {
                "index": 0,
                "model": "USB Camera",
                "device_id": "usb-stable-id",
                "serial": "usb-stable-id",
                "ip": "",
            }
        ]

    def open(self, device_id):
        assert device_id == "usb-stable-id"
        camera = FakeCamera()
        self.cameras.append(camera)
        return camera


@pytest.fixture
def native(tmp_path):
    config = CameraConsoleConfig.from_dict(
        {
            "source_type": "capture_uvc",
            "capture_uvc": {"device_id": "usb-stable-id"},
            "capture": {
                "photo_dir": str(tmp_path / "photos"),
                "video_dir": str(tmp_path / "videos"),
            },
        }
    )
    service = CaptureUvcService(lambda: config, core_factory=FakeCore)
    yield service, config
    service.close()


def test_native_config_round_trip_and_legacy_defaults(tmp_path):
    store = CameraConfigStore(tmp_path / "camera.yaml")
    config = CameraConsoleConfig.from_dict(
        {
            "source_type": "capture_uvc",
            "capture_uvc": {"device_id": "usb-id", "format_index": 3},
        }
    )
    store.save(config)
    assert store.load().to_dict() == config.to_dict()
    assert CameraConsoleConfig.from_dict({}).source_type == "mvs"
    with pytest.raises(ValueError, match="格式编号"):
        CameraConsoleConfig.from_dict({"capture_uvc": {"format_index": -2}})


def test_abi_struct_layouts_match_capturecore_header_on_64_bit():
    if ct.sizeof(ct.c_void_p) != 8:
        pytest.skip("本机 capturecore 为 64 位 ABI")
    assert [
        ct.sizeof(t)
        for t in (DeviceInfo, Format, Frame, Stats, RecordConfig, RecordResult)
    ] == [400, 16, 48, 24, 40, 312]
    assert Frame.data.offset == 32
    assert Frame.size.offset == 40
    assert ct.sizeof(PropOption) == 36
    assert ct.sizeof(PropMeta) == 696
    assert PropMeta.current.offset == 96
    assert PropMeta.options.offset == 116
    assert PropMeta.unit.offset == 692


def test_latest_frame_retries_buffer_growth_and_copies_owned_bytes():
    class GrowingDll:
        def cap_grab_latest(self, handle, buffer, capacity, output):
            frame = ct.cast(output, ct.POINTER(Frame)).contents
            frame.size = 10 if capacity == 0 else 20
            if capacity < frame.size:
                return 2
            ct.memmove(buffer, b"x" * 20, 20)
            frame.data = ct.addressof(buffer)
            frame.width, frame.height, frame.sequence = 16, 12, 7
            return 0

    core = SimpleNamespace(dll=GrowingDll(), check=lambda code: None)
    camera = CaptureCamera(core, ct.c_void_p(1))
    frame = camera.latest_frame()
    assert frame.data == b"x" * 20
    camera._buffer[0] = b"y"
    assert frame.data[0:1] == b"x"


def test_missing_library_error_is_actionable(tmp_path):
    with pytest.raises(CaptureError, match="找不到 Capture 内核"):
        CaptureCore(str(tmp_path / "missing.dll"))


def test_properties_read_live_values_instead_of_metadata_defaults():
    class PropertiesDll:
        def cap_prop_list(self, handle, output, count):
            ct.cast(count, ct.POINTER(ct.c_uint32)).contents.value = 1
            if output is not None:
                assert output[0].struct_size == ct.sizeof(PropMeta)
                output[0].id, output[0].name = 11, b"exposure_auto"
                output[0].type, output[0].current = 2, 0
                output[0].option_count = 2
                output[0].options[0] = PropOption(0, b"manual")
                output[0].options[1] = PropOption(1, b"auto")
            return 0

        def cap_prop_get(self, handle, property_id, value, automatic):
            assert property_id == 11
            ct.cast(value, ct.POINTER(ct.c_int64)).contents.value = 1
            ct.cast(automatic, ct.POINTER(ct.c_int32)).contents.value = 0
            return 0

    camera = CaptureCamera(
        SimpleNamespace(dll=PropertiesDll(), check=lambda code: None), ct.c_void_p(1)
    )
    prop = camera.properties()[0]
    assert prop["value"] == 1
    assert prop["options"] == [
        {"value": 0, "name": "manual"},
        {"value": 1, "name": "auto"},
    ]


@pytest.mark.parametrize("error", [1, 5, 7])
def test_boolean_property_uses_auto_interface_only_for_semantic_rejection(error):
    calls = []
    dll = SimpleNamespace(
        cap_prop_set=lambda *args: error,
        cap_prop_set_auto=lambda *args: calls.append(args) or 0,
    )
    checked = []
    camera = CaptureCamera(
        SimpleNamespace(dll=dll, check=checked.append), ct.c_void_p(1)
    )
    camera.set_property(8, 0, boolean=True)
    assert len(calls) == (0 if error == 7 else 1)
    assert checked == ([7] if error == 7 else [0])


def test_native_parameters_refresh_auto_locks_and_reject_invalid_writes(native):
    service, _ = native
    with pytest.raises(CaptureError, match="先连接"):
        service.get_parameters()
    service.connect()
    with pytest.raises(CaptureError, match="自动模式"):
        service.apply_parameters({"property_id": 9, "value": 4700})
    result = service.apply_parameters({"property_id": 8, "value": 0})
    assert not result["uvc_properties"][1]["is_auto"]
    result = service.apply_parameters({"property_id": 9, "value": 4700})
    assert result["uvc_properties"][1]["value"] == 4700
    for payload in (
        {"property_id": 9, "value": 4701},  # 不满足设备步长。
        {"property_id": 9, "value": 7000},
        {"property_id": 8, "value": 2},
        {"property_id": 11, "value": 2},  # 菜单范围内但不在可用选项中。
        {"property_id": 12, "value": 5000},  # 设备未暴露曝光时间。
        {"property_id": 8, "value": True},
        {"property_id": 8, "value": 0.5},
        {"exposure_us": 5000},
    ):
        with pytest.raises(CaptureError):
            service.apply_parameters(payload)
    service.apply_parameters({"property_id": 8, "value": 1})
    with pytest.raises(CaptureError, match="自动模式"):
        service.apply_parameters({"property_id": 9, "value": 4800})


def test_native_parameter_errors_and_empty_capabilities_are_not_hidden(native):
    service, _ = native
    service.connect()
    service._camera.properties = lambda: []
    assert service.get_parameters()["uvc_properties"] == []
    with pytest.raises(CaptureError, match="未提供"):
        service.apply_parameters({"property_id": 12, "value": 5000})

    def failed_read():
        raise CaptureError("设备属性读取失败")

    service._camera.properties = failed_read
    with pytest.raises(CaptureError, match="读取失败"):
        service.get_parameters()


def test_unchanged_frame_only_queries_metadata_without_copying():
    calls = []

    class MetadataDll:
        def cap_grab_latest(self, handle, buffer, capacity, output):
            calls.append((buffer, capacity))
            frame = ct.cast(output, ct.POINTER(Frame)).contents
            frame.sequence, frame.size = 42, 1000000
            return 2

    camera = CaptureCamera(
        SimpleNamespace(dll=MetadataDll(), check=lambda code: None), ct.c_void_p(1)
    )
    assert camera.latest_frame(after=42) is None
    assert calls == [(None, 0)]
    assert camera._buffer is None


@pytest.mark.parametrize(
    "fmt,data,expected",
    [
        (3, bytes([255, 0, 0]) * 4, [0, 0, 255]),
        (4, bytes([10, 20, 30, 255]) * 4, [10, 20, 30]),
        (1, bytes([16, 128, 16, 128]) * 2, [0, 0, 0]),
        (2, bytes([16] * 4 + [128, 128]), [0, 0, 0]),
    ],
)
def test_raw_formats_are_decoded_to_real_bgr(fmt, data, expected):
    image = decode_frame(CapturedFrame(0, 0, 2, 2, fmt, data))
    assert image.shape == (2, 2, 3)
    assert image[0, 0].tolist() == expected


def test_mjpeg_preview_and_snapshot_bypass_transcoding(native, monkeypatch):
    service, _ = native
    monkeypatch.setattr(
        "src.capture_uvc.service.decode_frame",
        lambda *args: pytest.fail("MJPEG 原尺寸不应解码"),
    )
    service.connect()
    _, jpeg, _ = service.wait_for_preview(-1)
    assert jpeg == service._camera.jpeg
    path = Path(service.save_snapshot())
    assert path.read_bytes() == jpeg
    assert service._camera.snapshots == [path]


def test_preview_resize_preserves_native_photo_and_video_size(native):
    service, config = native
    config.capture.output_max_width = 8
    config.capture.output_max_height = 6
    service.connect()
    _, jpeg, _ = service.wait_for_preview(-1)
    preview = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    photo = cv2.imread(service.save_snapshot())
    assert preview.shape[:2] == (6, 8)
    assert photo.shape[:2] == (12, 16)
    service.start_recording()
    assert service.status()["recording_size"] == [16, 12]


def test_raw_snapshot_is_encoded_as_jpeg_not_renamed_pixels(native):
    service, _ = native
    service.connect()
    service._camera.pixel_format = 3
    wait_until(lambda: service._frame.pixel_format == 3)
    path = service.save_snapshot()
    assert Path(path).read_bytes().startswith(b"\xff\xd8")
    assert cv2.imread(path).shape == (12, 16, 3)


@pytest.mark.parametrize("extension,mjpeg", [("avi", True), ("mp4", False)])
def test_recording_stays_in_native_core_and_reports_real_result(
    native, extension, mjpeg, monkeypatch
):
    service, config = native
    config.capture.video_format = extension
    monkeypatch.setattr(
        cv2,
        "VideoWriter",
        lambda *args: pytest.fail("原生录像不能经过 OpenCV VideoWriter"),
    )
    service.connect()
    path = service.start_recording()
    assert path.endswith("." + extension)
    assert service._camera.record_calls == [(Path(path), mjpeg)]
    assert service.status()["recording_dropped_frames"] is None
    assert service.stop_recording() == path
    assert service.status()["recording_result"]["frames_written"] == 42


def test_non_mjpeg_cannot_silently_use_avi_passthrough(native):
    service, config = native
    service.connect()
    service._camera.pixel_format = 3
    wait_until(lambda: service._frame.pixel_format == 3)
    config.capture.video_format = "avi"
    with pytest.raises(CaptureError, match="需要 MJPEG"):
        service.start_recording()
    assert not service._camera.record_calls


def test_auto_stop_and_disconnect_release_workers_and_finalize_recording(native):
    service, _ = native
    service.connect()
    camera = service._camera
    service.start_auto_capture(0.2)
    wait_until(lambda: len(camera.snapshots) >= 2)
    service.stop_auto_capture()
    count = len(camera.snapshots)
    assert not service._auto_worker.is_alive()
    service.start_recording()
    service.disconnect()
    assert camera.closed
    assert not camera.recording
    assert not service._worker.is_alive()
    assert len(camera.snapshots) == count


def test_stream_failure_stops_recording_and_is_reported(native):
    service, _ = native
    service.connect()
    service.start_recording()
    camera = service._camera
    camera.read_error = True
    wait_until(lambda: bool(service.status()["last_error"]))
    assert "模拟拔出" in service.status()["last_error"]
    assert service.status()["streaming"] is False
    assert camera.recording is False
    with pytest.raises(CaptureError, match="模拟拔出"):
        service.wait_for_preview(-1)
    assert service.wait_for_jpeg(-1)[1] is None


def test_slow_snapshot_keeps_preview_live_and_disconnect_waits_for_snapshot(native):
    service, _ = native
    service.connect()
    camera = service._camera
    started, release = threading.Event(), threading.Event()
    original_snapshot = camera.snapshot

    def slow_snapshot(path):
        started.set()
        assert release.wait(3)
        original_snapshot(path)

    camera.snapshot = slow_snapshot
    errors = []

    def capture():
        try:
            service.save_snapshot()
        except Exception as exc:
            errors.append(exc)

    snapshot = threading.Thread(target=capture)
    disconnect = threading.Thread(target=service.disconnect)
    snapshot.start()
    try:
        assert started.wait(2)
        sequence = service._preview_sequence
        wait_until(lambda: service._preview_sequence > sequence)
        assert service.status()["connected"]
        disconnect.start()
        time.sleep(0.03)
        assert not camera.closed
    finally:
        release.set()
        snapshot.join(3)
        if disconnect.ident:
            disconnect.join(3)
    assert not errors
    assert not snapshot.is_alive() and not disconnect.is_alive()
    assert camera.closed


def test_recording_finalize_failure_clears_recording_flag_and_reports_error(native):
    service, _ = native
    service.connect()
    service.start_recording()

    def fail():
        raise CaptureError("磁盘写入失败")

    service._camera.stop_recording = fail
    with pytest.raises(CaptureError, match="磁盘"):
        service.stop_recording()
    assert service.status()["recording"] is False
    assert "收尾失败" in service.status()["last_error"]


def test_web_routes_native_source_and_blocks_switch_while_connected(tmp_path):
    store = CameraConfigStore(tmp_path / "camera.yaml")
    store.save(
        CameraConsoleConfig.from_dict(
            {
                "source_type": "capture_uvc",
                "capture_uvc": {"device_id": "usb-stable-id"},
                "capture": {"photo_dir": str(tmp_path / "photos")},
            }
        )
    )
    shared = FrameCameraService(store)
    native = CaptureUvcService(lambda: shared.config, core_factory=FakeCore)
    client = create_app(service=shared, capture_service=native).test_client()
    try:
        assert (
            client.get("/api/devices?source=capture_uvc").get_json()["devices"][0][
                "device_id"
            ]
            == "usb-stable-id"
        )
        assert (
            client.get("/api/capture-uvc/formats?device_id=usb-stable-id").get_json()[
                "formats"
            ][0]["fps"]
            == 60
        )
        assert (
            client.post("/api/camera/connect").get_json()["status"]["source_type"]
            == "capture_uvc"
        )
        assert client.get("/api/camera/frame?after=-1").mimetype == "image/jpeg"
        assert (
            client.get("/api/camera/parameters").get_json()["parameters"][
                "uvc_properties"
            ][0]["id"]
            == 8
        )
        response = client.put(
            "/api/camera/parameters", json={"property_id": 8, "value": 0}
        )
        assert response.status_code == 200
        assert response.get_json()["parameters"]["uvc_properties"][0]["value"] == 0
        assert (
            client.put(
                "/api/camera/parameters", json={"property_id": 12, "value": 5000}
            ).status_code
            == 400
        )
        assert Path(client.post("/api/capture/snapshot").get_json()["path"]).exists()
        config = shared.config.to_dict()
        config["source_type"] = "mvs"
        response = client.put("/api/config", json=config)
        assert response.status_code == 400
        assert "先断开" in response.get_json()["error"]
        assert shared.config.source_type == "capture_uvc"
        config = shared.config.to_dict()
        config["capture"]["output_max_width"] = 8
        assert client.put("/api/config", json=config).status_code == 200
        assert client.put("/api/camera/roi", json={}).status_code == 400
        assert (
            client.post("/api/camera/disconnect").get_json()["status"]["connected"]
            is False
        )
    finally:
        native.close()
        shared.close()
