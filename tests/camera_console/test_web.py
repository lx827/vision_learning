from werkzeug.serving import WSGIRequestHandler

from src.camera_console.config import CameraConsoleConfig
from src.mvs.sdk import MvsError
from src.camera_console.web import (
    _QuietCameraRequestHandler,
    _camera_console_is_running,
    _schedule_browser_open,
    create_app,
)


class FakeWebService:
    def __init__(self):
        self.config = CameraConsoleConfig()
        self.enumerated_source = None

    def enumerate_devices(self, source_type=None):
        self.enumerated_source = source_type
        return [{"index": 0, "model": "FAKE-CAM", "serial": "T1", "ip": "192.168.1.20"}]

    def status(self):
        return {"connected": False, "streaming": False}

    def connect(self):
        raise MvsError("测试连接失败")

    def update_config(self, payload):
        self.config = CameraConsoleConfig.from_dict(payload)
        return self.config.to_dict()

    def apply_roi(self, payload):
        return {"applied_roi": payload}

    def set_processing_region(self, payload):
        return {**payload, "source_width": 64, "source_height": 48}

    def clear_processing_region(self):
        return None

    def wait_for_preview(self, sequence, timeout=2.0):
        return sequence + 1, b"\xff\xd8preview", 1_700_000_000_000


def test_request_handler_only_suppresses_successful_high_frequency_requests(monkeypatch):
    logged = []
    monkeypatch.setattr(
        WSGIRequestHandler,
        "log_request",
        lambda self, code="-", size="-": logged.append((self.path, code, size)),
    )
    handler = object.__new__(_QuietCameraRequestHandler)

    for path in ("/api/camera/frame?after=10", "/api/camera/status"):
        handler.path = path
        handler.log_request(200, 123)
        handler.log_request(204, 0)

    handler.path = "/api/camera/frame?after=10"
    handler.log_request(500, 0)
    handler.path = "/api/camera/connect"
    handler.log_request(200, 456)

    assert logged == [
        ("/api/camera/frame?after=10", 500, 0),
        ("/api/camera/connect", 200, 456),
    ]


def test_health_devices_and_config_api():
    service = FakeWebService()
    app = create_app(service=service)
    client = app.test_client()

    assert client.get("/api/health").get_json()["ok"] is True
    assert (
        client.get("/api/devices?source=droidcam_client").get_json()["devices"][0]["model"]
        == "FAKE-CAM"
    )
    assert service.enumerated_source == "droidcam_client"
    payload = client.get("/api/config").get_json()["config"]
    payload["camera"]["ip"] = "192.168.1.20"
    response = client.put("/api/config", json=payload)
    assert response.status_code == 200
    assert response.get_json()["config"]["camera"]["ip"] == "192.168.1.20"


def test_region_and_shared_output_size_controls_are_next_to_preview():
    app = create_app(service=FakeWebService())

    html = app.test_client().get("/").get_data(as_text=True)
    tools_start = html.index('<aside class="region-tools frame-source-only"')
    tools_end = html.index("</aside>", tools_start)
    tools = html[tools_start:tools_end]

    assert 'id="restore-full-roi-button"' in tools
    assert 'id="output-max-width"' in tools
    assert 'id="output-max-height"' in tools
    assert "当前采集区域" in tools


def test_camera_source_selector_has_three_peer_sources_and_one_control_set():
    app = create_app(service=FakeWebService())

    html = app.test_client().get("/").get_data(as_text=True)

    assert 'id="source-type"' in html
    assert '<option value="mvs">MVS 工业相机</option>' in html
    assert '<option value="droidcam_client">DroidCam 客户端</option>' in html
    assert '<option value="obs_droidcam">OBS DroidCam</option>' in html
    assert 'id="standard-camera-index"' in html
    assert 'id="standard-width"' in html
    assert 'id="standard-height"' in html
    assert 'id="standard-fps"' in html
    assert "只读取画面" in html
    assert "obs-panel" not in html
    assert html.count('id="snapshot-button"') == 1
    assert html.count('id="auto-button"') == 1
    assert html.count('id="record-button"') == 1
    assert 'id="event-log"' in html
    assert '<section class="panel stage"' in html
    assert '<label for="video-dir" id="video-dir-label">视频目录</label>' in html


def test_mvs_error_is_returned_as_json():
    app = create_app(service=FakeWebService())
    response = app.test_client().post("/api/camera/connect")

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "测试连接失败"}


def test_roi_api_forwards_camera_coordinates():
    app = create_app(service=FakeWebService())

    response = app.test_client().put(
        "/api/camera/roi",
        json={"width": 2048, "height": 2048, "centered": True},
    )

    assert response.status_code == 200
    assert response.get_json()["parameters"]["applied_roi"] == {
        "width": 2048,
        "height": 2048,
        "centered": True,
    }


def test_processing_region_api_keeps_separate_coordinates():
    app = create_app(service=FakeWebService())
    client = app.test_client()

    response = client.put(
        "/api/processing-region",
        json={"x": 4, "y": 6, "width": 20, "height": 10},
    )
    cleared = client.delete("/api/processing-region")

    assert response.get_json()["region"] == {
        "x": 4,
        "y": 6,
        "width": 20,
        "height": 10,
        "source_width": 64,
        "source_height": 48,
    }
    assert cleared.get_json()["region"] is None


def test_unknown_route_remains_not_found():
    app = create_app(service=FakeWebService())
    response = app.test_client().get("/missing")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


def test_latest_frame_endpoint_exposes_sequence_and_capture_time():
    app = create_app(service=FakeWebService())

    response = app.test_client().get("/api/camera/frame?after=4")

    assert response.status_code == 200
    assert response.data == b"\xff\xd8preview"
    assert response.headers["X-Frame-Sequence"] == "5"
    assert response.headers["X-Frame-Captured-At-Ms"] == "1700000000000"
    assert "no-store" in response.headers["Cache-Control"]


def test_browser_open_is_scheduled_in_daemon_timer(monkeypatch):
    opened = []
    timers = []

    class FakeTimer:
        def __init__(self, delay, callback, args):
            self.delay = delay
            self.callback = callback
            self.args = args
            self.daemon = False
            self.started = False
            timers.append(self)

        def start(self):
            self.started = True
            self.callback(*self.args)

    monkeypatch.setattr("src.camera_console.web.threading.Timer", FakeTimer)
    monkeypatch.setattr("src.camera_console.web.webbrowser.open", opened.append)

    _schedule_browser_open("http://127.0.0.1:8765")

    assert opened == ["http://127.0.0.1:8765"]
    assert timers[0].daemon is True
    assert timers[0].started is True


def test_existing_camera_console_is_detected(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"ok": true, "service": "camera-console"}'

    monkeypatch.setattr(
        "src.camera_console.web.urllib.request.urlopen", lambda *args, **kwargs: FakeResponse()
    )

    assert _camera_console_is_running("http://127.0.0.1:8765") is True
