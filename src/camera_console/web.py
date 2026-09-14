"""三种相机来源共用的浏览器控制台。"""

from __future__ import annotations

import atexit
import json
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.serving import WSGIRequestHandler

from .config import CameraConfigStore, CameraConsoleConfig
from src.mvs.sdk import MvsError
from .service import FrameCameraService
from src.droidcam.obs import ObsError, ObsService


class _QuietCameraRequestHandler(WSGIRequestHandler):
    """隐藏高频成功轮询，同时保留操作请求和错误访问日志。"""

    _QUIET_PATHS = {"/api/camera/frame", "/api/camera/status"}

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        try:
            status_code = int(str(code).split(maxsplit=1)[0])
        except (TypeError, ValueError):
            status_code = 0
        path = urlsplit(getattr(self, "path", "")).path
        if path in self._QUIET_PATHS and 200 <= status_code < 400:
            return
        super().log_request(code, size)


def create_app(
    config_path: str | Path = "configs/camera/camera.yaml",
    *,
    service: FrameCameraService | None = None,
    obs_service: ObsService | None = None,
) -> Flask:
    """创建可注入相机服务的 Web 应用。"""
    package_dir = Path(__file__).parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )
    camera_service = service or FrameCameraService(CameraConfigStore(config_path))
    app.config["MVS_SERVICE"] = camera_service
    obs = obs_service or ObsService()
    app.config["OBS_SERVICE"] = obs
    operation_lock = threading.RLock()

    def uses_obs() -> bool:
        return camera_service.config.source_type == "obs_droidcam"

    def normalized_obs_status() -> dict[str, Any]:
        status = obs.status()
        source = status["selected_source"]
        width, height = (status["last_photo_size"] + [0, 0])[:2]
        return {
            "connected": status["connected"] and bool(source),
            "source_type": "obs_droidcam",
            "streaming": False,
            "auto_capture": status["auto_capture"],
            "recording": status["recording"],
            "recording_path": status["recording_path"],
            "recording_seconds": status["recording_seconds"],
            "recording_fps": 0,
            "recording_dropped_frames": 0,
            "recording_duplicated_frames": 0,
            "recording_size": [],
            "fps_diagnostic": None,
            "last_photo": status["last_photo"],
            "last_error": status["error"],
            "fps": 0,
            "capture_fps": 0,
            "preview_fps": 0,
            "preview_rpc_ms": status["preview_rpc_ms"],
            "preview_frame_age_ms": 0,
            "preview_skipped_frames": 0,
            "frame_number": 0,
            "width": width,
            "height": height,
            "preview_width": 0,
            "preview_height": 0,
            "processing_region": None,
            "lost_packets": 0,
            "device": (
                {
                    "model": source,
                    "user_name": f"OBS {status['obs_version']}",
                    "serial": source,
                    "ip": "",
                    "transport": "obs-websocket",
                }
                if source
                else None
            ),
        }

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "service": "camera-console"})

    @app.get("/api/devices")
    def devices():
        source_type = request.args.get("source")
        if source_type == "obs_droidcam":
            was_connected = obs.status()["connected"]
            try:
                status = obs.connect()
                found = [
                    {
                        "index": index,
                        "model": source,
                        "serial": source,
                        "ip": "",
                        "user_name": "OBS DroidCam 输入源",
                        "transport": "obs-websocket",
                    }
                    for index, source in enumerate(status["sources"])
                ]
            finally:
                if not was_connected:
                    obs.disconnect()
            return _ok(devices=found)
        return _ok(devices=camera_service.enumerate_devices(source_type))

    @app.get("/api/config")
    def get_config():
        return _ok(config=camera_service.config.to_dict())

    @app.put("/api/config")
    def save_config():
        payload = _json_body()
        next_config = CameraConsoleConfig.from_dict(payload)
        current_config = camera_service.config
        if obs.status()["connected"] and (
            next_config.source_type != current_config.source_type
            or next_config.obs_droidcam != current_config.obs_droidcam
        ):
            raise ObsError("OBS DroidCam 已连接；修改来源前请先断开")
        return _ok(config=camera_service.update_config(payload))

    @app.get("/api/camera/status")
    def camera_status():
        return _ok(status=normalized_obs_status() if uses_obs() else camera_service.status())

    @app.post("/api/camera/connect")
    def camera_connect():
        with operation_lock:
            if uses_obs():
                if camera_service.status()["connected"]:
                    raise ObsError("请先断开当前帧相机，再连接 OBS DroidCam")
                config = camera_service.config
                source = config.obs_droidcam.source_name
                if not source:
                    raise ObsError("请先刷新设备并选择 OBS DroidCam 来源")
                obs.connect()
                try:
                    obs.select_source(source)
                    obs.prepare_scene()
                except Exception:
                    obs.disconnect()
                    raise
                return _ok(status=normalized_obs_status())
            if obs.status()["connected"]:
                raise MvsError("请先断开 OBS DroidCam，再连接其他相机来源")
            return _ok(status=camera_service.connect())

    @app.post("/api/camera/disconnect")
    def camera_disconnect():
        if uses_obs():
            obs.disconnect()
            return _ok(status=normalized_obs_status())
        return _ok(status=camera_service.disconnect())

    @app.get("/api/camera/parameters")
    def camera_parameters():
        if uses_obs():
            return _ok(parameters={"capabilities": {}, "controls_external": True})
        return _ok(parameters=camera_service.get_parameters())

    @app.put("/api/camera/parameters")
    def set_camera_parameters():
        if uses_obs():
            raise ObsError("OBS DroidCam 不提供工业相机成像参数")
        return _ok(parameters=camera_service.apply_parameters(_json_body()))

    @app.put("/api/camera/roi")
    def set_camera_roi():
        if uses_obs():
            raise ObsError("OBS DroidCam 不提供 MVS 硬件 ROI")
        return _ok(parameters=camera_service.apply_roi(_json_body()))

    @app.put("/api/processing-region")
    def set_processing_region():
        if uses_obs():
            raise ObsError("OBS DroidCam 临时方案不提供处理区域")
        return _ok(region=camera_service.set_processing_region(_json_body()))

    @app.delete("/api/processing-region")
    def clear_processing_region():
        camera_service.clear_processing_region()
        return _ok(region=None)

    @app.post("/api/capture/snapshot")
    def snapshot():
        if uses_obs():
            config = camera_service.config
            status = obs.snapshot(
                config.capture.photo_dir, config.obs_droidcam.photo_prefix
            )
            return _ok(path=status["last_photo"])
        return _ok(path=camera_service.save_snapshot())

    @app.post("/api/capture/auto/start")
    def auto_start():
        payload = _json_body(required=False)
        if uses_obs():
            config = camera_service.config
            status = obs.start_auto(
                payload.get("interval_seconds"),
                None,
                config.capture.photo_dir,
                config.obs_droidcam.photo_prefix,
            )
            return _ok(status=normalized_obs_status())
        return _ok(
            status=camera_service.start_auto_capture(payload.get("interval_seconds"))
        )

    @app.post("/api/capture/auto/stop")
    def auto_stop():
        if uses_obs():
            obs.stop_auto()
            return _ok(status=normalized_obs_status())
        return _ok(status=camera_service.stop_auto_capture())

    @app.post("/api/recording/start")
    def recording_start():
        if uses_obs():
            status = obs.start_recording(camera_service.config.capture.video_dir)
            return _ok(path=status["recording_path"], status=normalized_obs_status())
        return _ok(
            path=camera_service.start_recording(), status=camera_service.status()
        )

    @app.post("/api/recording/stop")
    def recording_stop():
        if uses_obs():
            status = obs.stop_recording()
            return _ok(path=status["recording_path"], status=normalized_obs_status())
        return _ok(path=camera_service.stop_recording(), status=camera_service.status())

    @app.get("/api/camera/stream")
    def camera_stream():
        if uses_obs():
            return Response(status=204, headers={"Cache-Control": "no-store"})
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

    @app.get("/api/camera/frame")
    def camera_frame():
        """一次只返回最新预览帧，避免浏览器积压 MJPEG 历史帧。"""
        if uses_obs():
            sequence, jpeg, requested_at_ms, rpc_ms = obs.preview_frame()
            return Response(
                jpeg,
                mimetype="image/jpeg",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "X-Frame-Sequence": str(sequence),
                    "X-Frame-Captured-At-Ms": str(requested_at_ms),
                    "X-Preview-Rpc-Ms": str(rpc_ms),
                },
            )
        after = request.args.get("after", default=-1, type=int)
        sequence, jpeg, captured_at_ms = camera_service.wait_for_preview(after)
        if jpeg is None or sequence == after:
            return Response(status=204, headers={"Cache-Control": "no-store"})
        return Response(
            jpeg,
            mimetype="image/jpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "X-Frame-Sequence": str(sequence),
                "X-Frame-Captured-At-Ms": str(captured_at_ms),
            },
        )

    @app.errorhandler(MvsError)
    @app.errorhandler(ObsError)
    @app.errorhandler(ValueError)
    def expected_error(error: Exception):
        return jsonify({"ok": False, "error": str(error)}), 400

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception):
        if isinstance(error, HTTPException):
            return jsonify({"ok": False, "error": error.description}), error.code
        app.logger.exception("相机控制台请求失败")
        return jsonify({"ok": False, "error": f"内部错误：{error}"}), 500

    if service is None:
        atexit.register(camera_service.close)
    if obs_service is None:
        atexit.register(obs.close)
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
    config_path: str | Path = "configs/camera/camera.yaml", *, open_browser: bool = True
) -> None:
    """使用配置文件启动本地调试服务。"""
    store = CameraConfigStore(config_path)
    config: CameraConsoleConfig = store.load()
    browser_host = (
        "127.0.0.1" if config.server.host in {"0.0.0.0", "::"} else config.server.host
    )
    url = f"http://{browser_host}:{config.server.port}"
    if _camera_console_is_running(url):
        print(
            f"相机调试台已由另一个进程运行：{url}\n"
            "本次命令没有启动新服务，因此此终端不会持续显示请求日志。"
        )
        if open_browser:
            webbrowser.open(url)
        return
    app = create_app(config_path)
    print(f"相机调试台：{url}")
    if open_browser:
        _schedule_browser_open(url)
    app.run(
        host=config.server.host,
        port=config.server.port,
        debug=False,
        threaded=True,
        use_reloader=False,
        request_handler=_QuietCameraRequestHandler,
    )


def _camera_console_is_running(url: str, timeout: float = 0.8) -> bool:
    """仅复用本项目已有服务；端口属于其他程序时仍交给 Flask 明确报错。"""
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return payload.get("ok") is True and payload.get("service") == "camera-console"


__all__ = [
    "_QuietCameraRequestHandler",
    "_camera_console_is_running",
    "create_app",
    "run",
]
