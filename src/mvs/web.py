"""MVS 浏览器调试台 Flask 应用。"""

from __future__ import annotations

import atexit
import threading
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from .config import MvsAppConfig, MvsConfigStore
from .sdk import MvsError
from .service import MvsCameraService


def create_app(
    config_path: str | Path = "configs/mvs/camera.yaml",
    *,
    service: MvsCameraService | None = None,
) -> Flask:
    """创建可注入相机服务的 Web 应用。"""
    package_dir = Path(__file__).parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )
    camera_service = service or MvsCameraService(MvsConfigStore(config_path))
    app.config["MVS_SERVICE"] = camera_service

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "service": "mvs-console"})

    @app.get("/api/devices")
    def devices():
        return _ok(devices=camera_service.enumerate_devices())

    @app.get("/api/config")
    def get_config():
        return _ok(config=camera_service.config.to_dict())

    @app.put("/api/config")
    def save_config():
        payload = _json_body()
        return _ok(config=camera_service.update_config(payload))

    @app.get("/api/camera/status")
    def camera_status():
        return _ok(status=camera_service.status())

    @app.post("/api/camera/connect")
    def camera_connect():
        return _ok(status=camera_service.connect())

    @app.post("/api/camera/disconnect")
    def camera_disconnect():
        return _ok(status=camera_service.disconnect())

    @app.get("/api/camera/parameters")
    def camera_parameters():
        return _ok(parameters=camera_service.get_parameters())

    @app.put("/api/camera/parameters")
    def set_camera_parameters():
        return _ok(parameters=camera_service.apply_parameters(_json_body()))

    @app.put("/api/camera/roi")
    def set_camera_roi():
        return _ok(parameters=camera_service.apply_roi(_json_body()))

    @app.put("/api/processing-region")
    def set_processing_region():
        return _ok(region=camera_service.set_processing_region(_json_body()))

    @app.delete("/api/processing-region")
    def clear_processing_region():
        camera_service.clear_processing_region()
        return _ok(region=None)

    @app.post("/api/capture/snapshot")
    def snapshot():
        return _ok(path=camera_service.save_snapshot())

    @app.post("/api/capture/auto/start")
    def auto_start():
        payload = _json_body(required=False)
        return _ok(
            status=camera_service.start_auto_capture(payload.get("interval_seconds"))
        )

    @app.post("/api/capture/auto/stop")
    def auto_stop():
        return _ok(status=camera_service.stop_auto_capture())

    @app.post("/api/recording/start")
    def recording_start():
        return _ok(
            path=camera_service.start_recording(), status=camera_service.status()
        )

    @app.post("/api/recording/stop")
    def recording_stop():
        return _ok(path=camera_service.stop_recording(), status=camera_service.status())

    @app.get("/api/camera/stream")
    def camera_stream():
        def generate():
            sequence = -1
            while True:
                sequence, jpeg = camera_service.wait_for_jpeg(sequence)
                if jpeg is None:
                    if not camera_service.status()["connected"]:
                        return
                    continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + jpeg + b"\r\n"

        return Response(
            generate(), mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    @app.errorhandler(MvsError)
    @app.errorhandler(ValueError)
    def expected_error(error: Exception):
        return jsonify({"ok": False, "error": str(error)}), 400

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        if isinstance(error, HTTPException):
            return jsonify({"ok": False, "error": error.description}), error.code
        app.logger.exception("MVS 调试台请求失败")
        return jsonify({"ok": False, "error": f"内部错误：{error}"}), 500

    if service is None:
        atexit.register(camera_service.close)
    return app


def _json_body(*, required: bool = True) -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if payload is None and not required:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return payload


def _ok(**payload: Any):
    return jsonify({"ok": True, **payload})


def _schedule_browser_open(url: str, delay: float = 1.0) -> None:
    """Open the console after Flask has had time to bind its local port."""
    timer = threading.Timer(delay, webbrowser.open, args=(url,))
    timer.daemon = True
    timer.start()


def run(
    config_path: str | Path = "configs/mvs/camera.yaml", *, open_browser: bool = True
) -> None:
    """使用配置文件启动本地调试服务。"""
    store = MvsConfigStore(config_path)
    config: MvsAppConfig = store.load()
    app = create_app(config_path)
    browser_host = (
        "127.0.0.1" if config.server.host in {"0.0.0.0", "::"} else config.server.host
    )
    url = f"http://{browser_host}:{config.server.port}"
    print(f"MVS 调试台：{url}")
    if open_browser:
        _schedule_browser_open(url)
    app.run(
        host=config.server.host,
        port=config.server.port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


__all__ = ["create_app", "run"]
