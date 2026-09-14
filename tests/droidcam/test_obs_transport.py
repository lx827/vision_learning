"""Optional wire-level tests: install websockets alongside requirements-obs.txt."""

import base64
import hashlib
import json
import threading

import pytest

pytest.importorskip("obsws_python")
server_module = pytest.importorskip("websockets.sync.server")

from src.droidcam.obs import ObsError, ObsService, make_client


@pytest.fixture
def wire_server(monkeypatch):
    requests = []
    closed = threading.Event()
    secret = base64.b64encode(hashlib.sha256(b"test-passwordsalt").digest()).decode()
    auth = base64.b64encode(
        hashlib.sha256((secret + "challenge").encode()).digest()
    ).decode()

    def handler(socket):
        try:
            socket.send(
                json.dumps(
                    {
                        "op": 0,
                        "d": {
                            "rpcVersion": 1,
                            "authentication": {
                                "salt": "salt",
                                "challenge": "challenge",
                            },
                        },
                    }
                )
            )
            identify = json.loads(socket.recv())
            if identify["d"].get("authentication") != auth:
                socket.close(code=4009, reason="Authentication failed")
                return
            socket.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
            for message in socket:
                data = json.loads(message)["d"]
                requests.append(data["requestType"])
                socket.send(
                    json.dumps(
                        {
                            "op": 7,
                            "d": {
                                "requestId": data["requestId"],
                                "requestType": data["requestType"],
                                "requestStatus": {
                                    "result": data["requestType"] != "MissingScene",
                                    "code": (
                                        600
                                        if data["requestType"] == "MissingScene"
                                        else 100
                                    ),
                                },
                                "responseData": {
                                    "obsVersion": "32.2.2",
                                    "obsWebSocketVersion": "5.7.4",
                                },
                            },
                        }
                    )
                )
        finally:
            closed.set()

    server = server_module.serve(handler, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OBS_WEBSOCKET_PORT", str(server.socket.getsockname()[1]))
    monkeypatch.setenv("OBS_WEBSOCKET_PASSWORD", "test-password")
    yield requests, closed
    server.shutdown()
    thread.join(timeout=3)


def test_real_client_authentication_rpc_errors_and_disconnect(wire_server, caplog):
    caplog.set_level("DEBUG")
    requests, closed = wire_server
    client = make_client()
    service = ObsService()
    service._client = client
    assert service._rpc("GetVersion")["obsVersion"] == "32.2.2"
    with pytest.raises(ObsError, match="600"):
        service._rpc("MissingScene")
    service.close()
    assert closed.wait(2)
    assert requests == ["GetVersion", "MissingScene"]
    # The mock server logs the derived challenge response; never the password.
    assert "test-password" not in caplog.text


def test_wrong_password_is_actionable_and_socket_is_closed(wire_server, monkeypatch):
    _, closed = wire_server
    monkeypatch.setenv("OBS_WEBSOCKET_PASSWORD", "wrong-password")
    with pytest.raises(ObsError, match="密码认证") as error:
        make_client()
    assert "wrong-password" not in str(error.value)
    assert closed.wait(2)
