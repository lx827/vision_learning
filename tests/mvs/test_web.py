from src.mvs.config import MvsAppConfig
from src.mvs.sdk import MvsError
from src.mvs.web import create_app


class FakeWebService:
    def __init__(self):
        self.config = MvsAppConfig()

    def enumerate_devices(self):
        return [{"index": 0, "model": "FAKE-CAM", "serial": "T1", "ip": "192.168.1.20"}]

    def status(self):
        return {"connected": False, "streaming": False}

    def connect(self):
        raise MvsError("测试连接失败")

    def update_config(self, payload):
        self.config = MvsAppConfig.from_dict(payload)
        return self.config.to_dict()


def test_health_devices_and_config_api():
    app = create_app(service=FakeWebService())
    client = app.test_client()

    assert client.get("/api/health").get_json()["ok"] is True
    assert client.get("/api/devices").get_json()["devices"][0]["model"] == "FAKE-CAM"
    payload = client.get("/api/config").get_json()["config"]
    payload["camera"]["ip"] = "192.168.1.20"
    response = client.put("/api/config", json=payload)
    assert response.status_code == 200
    assert response.get_json()["config"]["camera"]["ip"] == "192.168.1.20"


def test_mvs_error_is_returned_as_json():
    app = create_app(service=FakeWebService())
    response = app.test_client().post("/api/camera/connect")

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "测试连接失败"}


def test_unknown_route_remains_not_found():
    app = create_app(service=FakeWebService())
    response = app.test_client().get("/missing")

    assert response.status_code == 404
    assert response.get_json()["ok"] is False
