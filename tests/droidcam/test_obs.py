import json
import base64
from io import BytesIO
import time

import pytest
from PIL import Image

from src.camera_console.config import CameraConsoleConfig
from src.camera_console.web import create_app
from src.droidcam.config import ObsDroidCamConfig
from src.droidcam.obs import ObsError, ObsService, local_connection
from tests.camera_console.test_web import FakeWebService


class FakeObs:
    def __init__(self):
        self.calls = []
        self.current = "desktop-scene"
        self.scenes = {
            "desktop-scene": [{"sourceName": "Desktop", "sceneItemEnabled": True}]
        }
        self.recording = False
        self.closed = False
        self.failure = None
        self.cursor = 1
        self.photo_times = []
        self.desktop_muted = True
        self.record_directory = "C:/Videos"

    def disconnect(self):
        self.closed = True

    def send(self, name, data=None, raw=False):
        data = data or {}
        self.calls.append((name, data))
        if self.failure == name:
            raise TimeoutError("secret-password must not leak")
        if name == "GetVersion":
            return {"obsVersion": "32.2.2", "obsWebSocketVersion": "5.7.4"}
        if name == "GetInputList":
            return {
                "inputs": [
                    {"inputName": "my phone", "inputKind": "droidcam_obs"},
                    {"inputName": "Desktop", "inputKind": "monitor_capture"},
                ]
            }
        if name == "GetRecordStatus":
            return {
                "outputActive": self.recording,
                "outputDuration": 5000 if self.recording else 0,
            }
        if name == "GetStreamStatus":
            return {"outputActive": False}
        if name == "GetSpecialInputs":
            return {"desktop1": "Desktop audio", "mic1": None}
        if name == "GetInputMute":
            return {"inputMuted": self.desktop_muted}
        if name == "GetRecordDirectory":
            return {"recordDirectory": self.record_directory}
        if name == "SetRecordDirectory":
            self.record_directory = data["recordDirectory"]
        if name == "GetSceneList":
            return {
                "scenes": [{"sceneName": scene} for scene in self.scenes],
                "currentProgramSceneName": self.current,
            }
        if name == "GetCurrentProgramScene":
            return {"currentProgramSceneName": self.current}
        if name == "CreateScene":
            self.scenes[data["sceneName"]] = []
        elif name == "CreateSceneItem":
            self.scenes[data["sceneName"]].append(
                {"sourceName": data["sourceName"], "sceneItemEnabled": True}
            )
            return {"sceneItemId": 1}
        elif name == "GetSceneItemList":
            return {"sceneItems": self.scenes[data["sceneName"]]}
        elif name == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        elif name == "GetSceneTransitionList":
            return {
                "transitions": [
                    {"transitionName": "直接切换", "transitionKind": "cut_transition"}
                ]
            }
        elif name == "GetSourceFilterList":
            return {"filters": []}
        elif name == "GetCurrentSceneTransitionCursor":
            return {"transitionCursor": self.cursor}
        elif name == "SetCurrentProgramScene":
            self.current = data["sceneName"]
        elif name == "StartRecord":
            self.recording = True
        elif name == "StopRecord":
            self.recording = False
            return {"outputPath": "C:/Videos/phone.mkv"}
        elif name == "SaveSourceScreenshot":
            self.photo_times.append(time.monotonic())
            Image.new("RGB", (64, 48), "green").save(data["imageFilePath"])
        elif name == "GetSourceScreenshot":
            image = BytesIO()
            Image.new("RGB", (96, 54), "green").save(image, format="JPEG")
            return {
                "imageData": "data:image/jpeg;base64,"
                + base64.b64encode(image.getvalue()).decode("ascii")
            }
        return {}


@pytest.fixture
def rig(tmp_path):
    remote = FakeObs()
    service = ObsService(client_factory=lambda: remote, output_root=tmp_path)
    service.connect()
    service.select_source("my phone")
    yield service, remote
    service.close()


def test_phone_scene_does_not_modify_desktop_and_records_only_phone(rig):
    service, remote = rig
    result = service.prepare_scene()
    assert remote.scenes["desktop-scene"] == [
        {"sourceName": "Desktop", "sceneItemEnabled": True}
    ]
    assert remote.scenes[result["phone_scene"]] == [
        {"sourceName": "my phone", "sceneItemEnabled": True}
    ]
    transform = next(
        data["sceneItemTransform"]
        for name, data in remote.calls
        if name == "SetSceneItemTransform"
    )
    assert transform["boundsType"] == "OBS_BOUNDS_SCALE_INNER"
    assert transform["cropLeft"] == transform["cropRight"] == 0
    assert service.start_recording()["recording"] is True
    assert service.stop_recording()["recording_path"].endswith("phone.mkv")


def test_existing_safe_phone_scene_is_reused_after_service_restart(rig, tmp_path):
    service, remote = rig
    first_scene = service.prepare_scene()["phone_scene"]
    creates_before = len([name for name, _ in remote.calls if name == "CreateScene"])
    restarted = ObsService(client_factory=lambda: remote, output_root=tmp_path)
    try:
        restarted.connect()
        restarted.select_source("my phone")
        assert restarted.prepare_scene()["phone_scene"] == first_scene
        creates_after = len([name for name, _ in remote.calls if name == "CreateScene"])
        assert creates_after == creates_before
    finally:
        restarted.close()


@pytest.mark.parametrize("change", ["desktop", "disabled", "switched", "transition"])
def test_unsafe_scene_cannot_start_recording(rig, change):
    service, remote = rig
    scene = service.prepare_scene()["phone_scene"]
    if change == "desktop":
        remote.scenes[scene].append(
            {"sourceName": "Desktop", "sceneItemEnabled": False}
        )
    elif change == "disabled":
        remote.scenes[scene][0]["sceneItemEnabled"] = False
    elif change == "switched":
        remote.current = "desktop-scene"
    else:
        remote.cursor = 0.5
    with pytest.raises(ObsError):
        service.start_recording()
    assert not any(name == "StartRecord" for name, _ in remote.calls)


def test_desktop_and_missing_sources_are_rejected(rig):
    service, remote = rig
    assert service.status()["sources"] == ["my phone"]
    for source in ("Desktop", "missing"):
        with pytest.raises(ObsError):
            service.select_source(source)


def test_global_desktop_audio_blocks_phone_recording(rig):
    service, remote = rig
    service.prepare_scene()
    remote.desktop_muted = False
    with pytest.raises(ObsError, match="桌面音频"):
        service.start_recording()
    assert not remote.recording


def test_stop_waits_until_obs_finishes_the_output(tmp_path):
    remote = FakeObs()
    remote.recording = True
    original_send = remote.send
    remaining = 0

    def delayed_stop(name, data=None, raw=False):
        nonlocal remaining
        if name == "StopRecord":
            remaining = 3
            return {"outputPath": "C:/Videos/phone.mkv"}
        if name == "GetRecordStatus" and remaining:
            remaining -= 1
            if remaining == 0:
                remote.recording = False
        return original_send(name, data, raw)

    remote.send = delayed_stop
    service = ObsService(output_root=tmp_path)
    service._client = remote
    service._owned_recording = True
    try:
        result = service.stop_recording()
        assert not result["recording"]
        assert remaining == 0
        assert result["recording_path"].endswith("phone.mkv")
    finally:
        service.close()


def test_screenshots_address_input_and_verify_file(rig):
    service, remote = rig
    first = service.snapshot()["last_photo"]
    second = service.snapshot()["last_photo"]
    assert first != second
    assert service.status()["last_photo_size"] == [64, 48]
    photos = [data for name, data in remote.calls if name == "SaveSourceScreenshot"]
    assert len(photos) == 2
    assert all(data["sourceName"] == "my phone" for data in photos)
    assert not any(name == "GetSourceScreenshot" for name, _ in remote.calls)
    with Image.open(first) as image:
        assert image.format == "PNG"


def test_low_rate_preview_returns_valid_source_jpeg(rig):
    service, remote = rig
    sequence, jpeg, requested_at_ms, rpc_ms = service.preview_frame()

    assert sequence == 1
    assert jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")
    assert requested_at_ms > 0
    assert rpc_ms >= 0
    request = next(data for name, data in remote.calls if name == "GetSourceScreenshot")
    assert request["sourceName"] == "my phone"
    assert request["imageWidth"] == 960


def test_recording_directory_is_applied_for_one_recording_and_restored(rig, tmp_path):
    service, remote = rig
    service.prepare_scene()
    original = remote.record_directory

    service.start_recording(str(tmp_path / "chosen-videos"))
    assert remote.record_directory == str((tmp_path / "chosen-videos").resolve())
    service.stop_recording()

    assert remote.record_directory == original
    assert (tmp_path / "chosen-videos").is_dir()


def test_automatic_schedule_stops_at_duration_without_duplicate_names(rig):
    service, remote = rig
    service.start_auto(0.2, 0.65)
    deadline = time.monotonic() + 3
    while service.status()["auto_capture"] and time.monotonic() < deadline:
        time.sleep(0.02)
    status = service.status()
    assert not status["auto_capture"]
    assert 3 <= status["auto_count"] <= 4
    assert all(
        b - a >= 0.14 for a, b in zip(remote.photo_times, remote.photo_times[1:])
    )
    paths = [
        data["imageFilePath"]
        for name, data in remote.calls
        if name == "SaveSourceScreenshot"
    ]
    assert len(paths) == len(set(paths))


@pytest.mark.parametrize(
    "interval,duration",
    [(0, 10), (float("nan"), 10), (1, float("inf")), (2, 1)],
)
def test_invalid_auto_parameters_do_not_start(rig, interval, duration):
    service, _ = rig
    with pytest.raises(ObsError):
        service.start_auto(interval, duration)
    assert not service.status()["auto_capture"]


def test_automatic_schedule_can_run_until_manually_stopped(rig):
    service, remote = rig
    service.start_auto(0.2, None)
    deadline = time.monotonic() + 2
    while len(remote.photo_times) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    service.stop_auto()

    assert len(remote.photo_times) >= 2
    assert service.status()["auto_capture"] is False


def test_stop_auto_and_close_release_workers(rig):
    service, remote = rig
    service.start_auto(10, 20)
    service.stop_auto()
    count = len(remote.photo_times)
    time.sleep(0.1)
    assert len(remote.photo_times) == count
    service.close()
    assert remote.closed
    assert not service._worker.is_alive()


def test_lost_start_response_is_not_replayed_and_reconnect_stops_recording(
    rig, tmp_path
):
    service, remote = rig
    service.prepare_scene()
    remote.failure = "StartRecord"
    with pytest.raises(ObsError, match="不会自动重放") as error:
        service.start_recording(str(tmp_path / "uncertain-recording"))
    assert "secret-password" not in str(error.value)
    assert not service.status()["recording_known"]
    remote.recording = True  # OBS performed the operation but its reply was lost.
    remote.failure = None
    service.connect()
    assert not remote.recording
    assert remote.record_directory == "C:/Videos"
    assert len([name for name, _ in remote.calls if name == "StartRecord"]) == 1


def test_monitor_stops_when_scene_is_changed_during_recording(rig):
    service, remote = rig
    service.prepare_scene()
    service.start_recording()
    remote.current = "desktop-scene"
    deadline = time.monotonic() + 3
    while remote.recording and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not remote.recording
    assert "节目场景" in service.status()["error"]


def test_local_credentials_stay_backend_only(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("OBS_WEBSOCKET_PASSWORD", raising=False)
    monkeypatch.delenv("OBS_WEBSOCKET_PORT", raising=False)
    path = tmp_path / "obs-studio/plugin_config/obs-websocket/config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {"server_enabled": True, "server_port": 4456, "server_password": "private"}
        )
    )
    assert local_connection()["password"] == "private"
    assert local_connection()["port"] == 4456
    path.write_text(json.dumps({"server_enabled": False}))
    with pytest.raises(ObsError, match="未启用"):
        local_connection()


def test_http_actions_and_credentials_boundary(rig):
    service, _ = rig
    camera = FakeWebService()
    camera.config = CameraConsoleConfig(
        source_type="obs_droidcam",
        obs_droidcam=ObsDroidCamConfig(source_name="my phone"),
    )
    client = create_app(service=camera, obs_service=service).test_client()

    assert client.post("/api/camera/connect").status_code == 200
    status_response = client.get("/api/camera/status")
    assert status_response.json["status"]["connected"]
    assert "password" not in status_response.get_data(as_text=True)
    assert client.get("/api/obs/status").status_code == 404
    preview = client.get("/api/camera/frame?after=-1")
    assert preview.status_code == 200
    assert preview.mimetype == "image/jpeg"
    assert preview.headers["X-Preview-Rpc-Ms"]
    assert client.post("/api/recording/start").json["status"]["recording"]
    assert client.post("/api/recording/stop").json["status"]["recording"] is False
    assert client.post("/api/capture/snapshot").json["path"]
    assert client.post("/api/capture/auto/start", json={}).status_code == 400
    assert client.post(
        "/api/capture/auto/start", json={"interval_seconds": 1}
    ).status_code == 200
    assert client.post("/api/capture/auto/stop").json["status"]["auto_capture"] is False
    assert client.post("/api/camera/disconnect").json["status"]["connected"] is False


def test_frame_camera_and_obs_connections_are_mutually_exclusive(rig):
    service, _ = rig
    camera = FakeWebService()
    camera.config.source_type = "droidcam_client"
    client = create_app(service=camera, obs_service=service).test_client()
    assert "断开 OBS" in client.post("/api/camera/connect").json["error"]
    camera.config.source_type = "obs_droidcam"
    camera.config.obs_droidcam.source_name = "my phone"
    camera.status = lambda: {"connected": True}
    assert "断开当前帧相机" in client.post("/api/camera/connect").json["error"]
