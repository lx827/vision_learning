"""OBS DroidCam control, isolated from MVS and DroidCam Client acquisition.

OBS records its program output. Only a new scene containing the selected
DroidCam input may be used here; screenshots address the input directly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ObsError(Exception):
    """An actionable, credential-free error suitable for the browser."""


def _close_client(client):
    try:
        client.disconnect()
    finally:
        # websocket-client's close() returns early after receiving a close frame.
        # In particular an auth rejection can otherwise leave its TCP socket open.
        base = getattr(client, "base_client", None)
        if base is not None:
            base.ws.shutdown()


def local_connection() -> dict[str, Any]:
    """Read OBS's own local settings at connect time; never return them to HTTP."""
    config_path = (
        Path(os.environ.get("APPDATA", ""))
        / "obs-studio/plugin_config/obs-websocket/config.json"
    )
    config = {}
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise ObsError("无法读取本机 OBS WebSocket 设置") from None
    port = int(os.environ.get("OBS_WEBSOCKET_PORT", config.get("server_port", 4455)))
    if not 1 <= port <= 65535:
        raise ObsError("OBS WebSocket 端口必须在 1～65535 之间")
    if config.get("server_enabled") is False and "OBS_WEBSOCKET_PORT" not in os.environ:
        raise ObsError(
            "OBS WebSocket 未启用：请在 OBS 的工具 → WebSocket 服务器设置中启用服务"
        )
    return {
        "host": "127.0.0.1",
        "port": port,
        "password": os.environ.get(
            "OBS_WEBSOCKET_PASSWORD", config.get("server_password", "")
        ),
        "timeout": 3,
    }


def make_client():
    settings = local_connection()
    try:
        from obsws_python import ReqClient
    except ImportError:
        raise ObsError("缺少 OBS 可选依赖，请安装 requirements-obs.txt") from None
    # This SDK logs plaintext connection credentials at INFO and raw RPC at DEBUG.
    # Suppress those library loggers; only our sanitized errors leave this module.
    for name in ("obsws_python.baseclient.ObsClient", "obsws_python.reqs.ReqClient"):
        logging.getLogger(name).disabled = True
    client = ReqClient.__new__(ReqClient)
    try:
        client.__init__(**settings)
        return client
    except Exception as error:
        if hasattr(client, "base_client"):
            try:
                _close_client(client)
            except Exception:
                pass
        if "auth" in str(error).lower() or "identify" in str(error).lower():
            raise ObsError(
                "OBS 密码认证失败，请检查后端密码与 OBS 的认证设置"
            ) from None
        raise ObsError(
            "无法连接 OBS，请检查 OBS 是否运行、WebSocket 端口是否正确或服务是否超时"
        ) from None


class ObsService:
    def __init__(self, *, client_factory=make_client, output_root: Path | None = None):
        self._factory = client_factory
        self._root = output_root or Path(__file__).resolve().parents[2]
        self._lock = threading.RLock()
        self._client = None
        self._desired = False
        self._shutdown = threading.Event()
        self._worker = None
        self._retry_at = 0.0
        self._owned_recording = False
        self._recording_uncertain = False
        self._recording_directory_restore = ""
        self._auto = None
        self._state = {
            "connected": False,
            "obs_version": "",
            "websocket_version": "",
            "current_scene": "",
            "sources": [],
            "selected_source": "",
            "phone_scene": "",
            "recording": False,
            "recording_known": False,
            "recording_seconds": 0.0,
            "recording_path": "",
            "recording_directory": "",
            "preview_sequence": 0,
            "preview_rpc_ms": 0.0,
            "auto_capture": False,
            "auto_count": 0,
            "auto_skipped": 0,
            "last_photo": "",
            "last_photo_size": [],
            "error": "",
        }

    def _drop_client(self):
        client, self._client = self._client, None
        if client:
            try:
                _close_client(client)
            except Exception:
                pass
        self._state.update(connected=False, recording_known=False)

    def _rpc(self, request: str, **data) -> dict:
        if self._client is None:
            raise ObsError("OBS 未连接，请先检查连接")
        try:
            return self._client.send(request, data or None, raw=True) or {}
        except Exception as error:
            code = getattr(error, "code", None)
            if code is not None:
                raise ObsError(
                    f"OBS 拒绝 {request}（错误码 {code}）；请检查场景、输入源或输出状态"
                ) from None
            self._recording_uncertain = self._owned_recording
            self._drop_client()
            self._auto = None
            self._state["auto_capture"] = False
            raise ObsError(
                f"OBS 通信中断或超时（{request}）；操作结果可能未知，请检查 OBS。不会自动重放此操作"
            ) from None

    def _sources(self):
        inputs = self._rpc("GetInputList")["inputs"]
        return [
            i["inputName"]
            for i in inputs
            if i.get("unversionedInputKind", i.get("inputKind")) == "droidcam_obs"
        ]

    def _require_source(self):
        source = self._state["selected_source"]
        if not source or source not in self._sources():
            raise ObsError("所选 DroidCam OBS 输入源不存在，请刷新并重新选择手机源")
        return source

    def _require_idle(self):
        if self._rpc("GetRecordStatus")["outputActive"]:
            raise ObsError("OBS 正在录像，请先停止录像再更换手机源或准备场景")
        if self._rpc("GetStreamStatus")["outputActive"]:
            raise ObsError("OBS 正在直播，请先停止直播再切换手机专用场景")

    def _verify_scene(self, *, current=True):
        source = self._require_source()
        scene = self._state["phone_scene"]
        if not scene:
            raise ObsError("请先准备手机专用场景")
        items = self._rpc("GetSceneItemList", sceneName=scene)["sceneItems"]
        if (
            len(items) != 1
            or items[0]["sourceName"] != source
            or not items[0]["sceneItemEnabled"]
        ):
            raise ObsError(
                "手机专用场景被修改：必须且只能包含一个启用的所选 DroidCam 源"
            )
        if (
            current
            and self._rpc("GetCurrentProgramScene")["currentProgramSceneName"] != scene
        ):
            raise ObsError("OBS 当前节目场景不是手机专用场景，请重新准备场景")
        if self._rpc("GetSourceFilterList", sourceName=scene)["filters"]:
            raise ObsError("手机专用场景含额外滤镜，请移除后重试")
        cursor = self._rpc("GetCurrentSceneTransitionCursor")["transitionCursor"]
        if 0 < cursor < 1:
            raise ObsError("OBS 正在转场，请等待转场结束后再录像")

    def _verify_audio(self):
        source = self._state["selected_source"]
        for name in self._rpc("GetSpecialInputs").values():
            if (
                name
                and name != source
                and not self._rpc("GetInputMute", inputName=name)["inputMuted"]
            ):
                raise ObsError(
                    "OBS 仍启用了桌面音频或全局麦克风；请先静音这两类非手机音频。DroidCam OBS 自身音频可按需保留"
                )

    def _scene_names(self) -> list[str]:
        return [
            scene["sceneName"]
            for scene in self._rpc("GetSceneList").get("scenes", [])
            if scene.get("sceneName")
        ]

    def _reusable_phone_scene(self, source: str) -> str:
        names = self._scene_names()
        current = self._rpc("GetCurrentProgramScene")["currentProgramSceneName"]
        candidates = ([current] if current in names else []) + [
            name
            for name in names
            if name != current and name.startswith("手机采集-")
        ]
        for scene in candidates:
            if not scene.startswith("手机采集-"):
                continue
            items = self._rpc("GetSceneItemList", sceneName=scene)["sceneItems"]
            if (
                len(items) == 1
                and items[0]["sourceName"] == source
                and items[0]["sceneItemEnabled"]
                and not self._rpc("GetSourceFilterList", sourceName=scene)["filters"]
            ):
                return scene
        return ""

    def connect(self):
        with self._lock:
            self._desired = True
            try:
                if self._client is None:
                    self._client = self._factory()
                self._refresh()
                if not self._state["error"].startswith("连接曾中断"):
                    self._state["error"] = ""
            except ObsError as error:
                self._state["error"] = str(error)
                self._drop_client()
                self._retry_at = time.monotonic() + 3
                raise
            finally:
                if self._worker is None:
                    self._worker = threading.Thread(
                        target=self._loop, name="obs-control", daemon=True
                    )
                    self._worker.start()
            return self.status()

    def _refresh(self):
        version = self._rpc("GetVersion")
        record = self._rpc("GetRecordStatus")
        if self._recording_uncertain and record["outputActive"]:
            # Reconnection cannot establish what was recorded during the gap.
            self._finish_recording()
            self._state["error"] = (
                "连接曾中断，已停止本项目录像；请检查文件中断线期间的内容"
            )
            record = self._rpc("GetRecordStatus")
        if not record["outputActive"]:
            self._owned_recording = False
            self._recording_uncertain = False
            if self._recording_directory_restore:
                self._restore_recording_directory()
        self._state.update(
            connected=True,
            obs_version=version["obsVersion"],
            websocket_version=version["obsWebSocketVersion"],
            sources=self._sources(),
            current_scene=self._rpc("GetCurrentProgramScene")[
                "currentProgramSceneName"
            ],
            recording=record["outputActive"],
            recording_known=True,
            recording_seconds=record.get("outputDuration", 0) / 1000,
            recording_directory=self._rpc("GetRecordDirectory")["recordDirectory"],
        )

    def status(self):
        with self._lock:
            return {**self._state, "sources": list(self._state["sources"])}

    def select_source(self, source: str):
        with self._lock:
            self._require_idle()
            if self._auto:
                raise ObsError("请先停止自动拍照再切换手机源")
            if source not in self._sources():
                raise ObsError("输入源不存在或不是 DroidCam OBS 手机源")
            if source != self._state["selected_source"]:
                self._state.update(selected_source=source, phone_scene="")
            return self.status()

    def prepare_scene(self):
        with self._lock:
            self._require_idle()
            source = self._require_source()
            scene = self._state["phone_scene"]
            if not scene:
                scene = self._reusable_phone_scene(source)
                if not scene:
                    scene = f"手机采集-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}"
                    if scene in self._scene_names():
                        raise ObsError(
                            "固定手机专用场景已存在但内容不安全；请在 OBS 中检查该场景后重试"
                        )
                    self._rpc("CreateScene", sceneName=scene)
                    item = self._rpc(
                        "CreateSceneItem",
                        sceneName=scene,
                        sourceName=source,
                        sceneItemEnabled=True,
                    )
                    video = self._rpc("GetVideoSettings")
                    self._rpc(
                        "SetSceneItemTransform",
                        sceneName=scene,
                        sceneItemId=item["sceneItemId"],
                        sceneItemTransform={
                            "positionX": 0.0,
                            "positionY": 0.0,
                            "rotation": 0.0,
                            "alignment": 5,
                            "boundsType": "OBS_BOUNDS_SCALE_INNER",
                            "boundsAlignment": 0,
                            "boundsWidth": video["baseWidth"],
                            "boundsHeight": video["baseHeight"],
                            "cropLeft": 0,
                            "cropRight": 0,
                            "cropTop": 0,
                            "cropBottom": 0,
                        },
                    )
                    transitions = self._rpc("GetSceneTransitionList")["transitions"]
                    cut = next(
                        (
                            t["transitionName"]
                            for t in transitions
                            if t["transitionKind"] == "cut_transition"
                        ),
                        None,
                    )
                    if not cut:
                        raise ObsError("OBS 缺少直接切换转场，无法安全准备手机场景")
                    self._rpc(
                        "SetSceneSceneTransitionOverride",
                        sceneName=scene,
                        transitionName=cut,
                    )
                self._state["phone_scene"] = scene
            self._verify_scene(current=False)
            self._rpc("SetCurrentProgramScene", sceneName=scene)
            self._verify_scene()
            self._refresh()
            return self.status()

    def _recording_directory(self, directory: str) -> str:
        if not isinstance(directory, str) or not directory.strip():
            raise ObsError("录像保存目录不能为空")
        folder = Path(directory).expanduser()
        if not folder.is_absolute():
            folder = self._root / folder
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ObsError("无法创建录像目录，请检查路径和写入权限") from None
        return str(folder.resolve())

    def _restore_recording_directory(self):
        directory = self._recording_directory_restore
        if directory and self._client is not None:
            self._rpc("SetRecordDirectory", recordDirectory=directory)
            self._recording_directory_restore = ""

    def start_recording(self, directory: str | None = None):
        with self._lock:
            self._require_idle()
            self._verify_scene()
            self._verify_audio()
            current_directory = self._rpc("GetRecordDirectory")["recordDirectory"]
            target_directory = (
                current_directory
                if directory is None
                else self._recording_directory(directory)
            )
            if Path(target_directory) != Path(current_directory):
                self._rpc("SetRecordDirectory", recordDirectory=target_directory)
                self._recording_directory_restore = current_directory
            # Mark ownership before sending: a lost response must never replay StartRecord.
            self._owned_recording = True
            try:
                self._rpc("StartRecord")
            except ObsError:
                if self._client is not None:
                    self._owned_recording = False
                    self._restore_recording_directory()
                raise
            self._refresh()
            return self.status()

    def stop_recording(self):
        with self._lock:
            if self._rpc("GetRecordStatus")["outputActive"]:
                self._finish_recording()
            self._owned_recording = False
            self._refresh()
            return self.status()

    def _finish_recording(self):
        self._state["recording_path"] = self._rpc("StopRecord").get("outputPath", "")
        deadline = time.monotonic() + 15
        # StopRecord acknowledges the request before the encoder/muxer finishes.
        # Do not report completion or restore output settings while still active.
        while self._rpc("GetRecordStatus")["outputActive"]:
            if time.monotonic() >= deadline:
                raise ObsError(
                    "OBS 仍在结束录像，尚未确认文件写入完成；请稍候检查 OBS 状态"
                )
            time.sleep(0.1)
        self._owned_recording = False
        self._recording_uncertain = False
        self._restore_recording_directory()

    def preview_frame(self, *, width: int = 960, quality: int = 70):
        """Return a low-rate JPEG preview of the selected input source."""
        with self._lock:
            source = self._require_source()
            requested_at_ms = int(time.time() * 1000)
            started = time.perf_counter()
            response = self._rpc(
                "GetSourceScreenshot",
                sourceName=source,
                imageFormat="jpg",
                imageWidth=width,
                imageCompressionQuality=quality,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            encoded = response.get("imageData", "").partition(",")[2]
            try:
                jpeg = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise ObsError("OBS 返回了无效的预览图像") from None
            if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                raise ObsError("OBS 返回的预览图像不是有效 JPEG")
            self._state["preview_sequence"] += 1
            self._state["preview_rpc_ms"] = round(elapsed_ms, 1)
            return (
                self._state["preview_sequence"],
                jpeg,
                requested_at_ms,
                self._state["preview_rpc_ms"],
            )

    def _photo_options(self, directory, prefix):
        if not isinstance(directory, str) or not directory.strip():
            raise ObsError("照片保存目录不能为空")
        if not isinstance(prefix, str) or not re.fullmatch(r"[\w-]{1,64}", prefix):
            raise ObsError("文件名前缀限 1～64 个字母、数字、中文、下划线或连字符")
        folder = Path(directory).expanduser()
        if not folder.is_absolute():
            folder = self._root / folder
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ObsError("无法创建照片目录，请检查路径和写入权限") from None
        return folder.resolve(), prefix

    def snapshot(self, directory="data/obs/photos", prefix="phone"):
        with self._lock:
            source = self._require_source()
            folder, prefix = self._photo_options(directory, prefix)
            path = (
                folder
                / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:8]}.png"
            )
            self._rpc(
                "SaveSourceScreenshot",
                sourceName=source,
                imageFormat="png",
                imageFilePath=str(path),
            )
            try:
                from PIL import Image

                with Image.open(path) as picture:
                    size = list(picture.size)
                    if picture.format != "PNG" or min(size) <= 0:
                        raise ValueError("Invalid image")
                    picture.verify()
            except (OSError, ValueError):
                raise ObsError(
                    "OBS 返回截图成功，但本机未找到有效 PNG 文件，请检查 OBS 写入权限"
                ) from None
            self._state.update(last_photo=str(path), last_photo_size=size)
            return self.status()

    def start_auto(
        self,
        interval_seconds,
        duration_seconds=None,
        directory="data/obs/photos",
        prefix="phone",
    ):
        with self._lock:
            self._require_source()
            if self._auto:
                raise ObsError("自动拍照已经运行，请先停止")
            try:
                interval = float(interval_seconds)
                duration = (
                    None if duration_seconds is None else float(duration_seconds)
                )
            except (ValueError, TypeError):
                raise ObsError("自动拍照间隔和总时长必须是数字") from None
            if not math.isfinite(interval) or not 0.2 <= interval <= 86400:
                raise ObsError("自动拍照间隔必须在 0.2～86400 秒之间")
            if duration is not None and (
                not math.isfinite(duration) or not interval <= duration <= 86400
            ):
                raise ObsError("总时长必须不小于间隔且不超过 86400 秒")
            folder, prefix = self._photo_options(directory, prefix)
            now = time.monotonic()
            self._auto = dict(
                interval=interval,
                end=None if duration is None else now + duration,
                next=now,
                directory=str(folder),
                prefix=prefix,
            )
            self._state.update(
                auto_capture=True, auto_count=0, auto_skipped=0, error=""
            )
            return self.status()

    def stop_auto(self):
        with self._lock:
            self._auto = None
            self._state["auto_capture"] = False
            return self.status()

    def _tick_auto(self, now):
        job = self._auto
        if not job:
            return
        if job["end"] is not None and now >= job["end"]:
            self.stop_auto()
        elif now >= job["next"]:
            self.snapshot(job["directory"], job["prefix"])
            self._state["auto_count"] += 1
            job["next"] += job["interval"]
            # No burst catch-up when disk/RPC is slow; keep a monotonic schedule.
            completed = time.monotonic()
            if job["next"] < completed:
                missed = math.ceil((completed - job["next"]) / job["interval"])
                job["next"] += missed * job["interval"]
                self._state["auto_skipped"] += missed

    def _loop(self):
        refresh_at = 0.0
        while not self._shutdown.wait(0.05):
            with self._lock:
                if not self._desired:
                    continue
                now = time.monotonic()
                try:
                    if self._client is None:
                        if now < self._retry_at:
                            continue
                        self._retry_at = now + 3
                        self._client = self._factory()
                        self._refresh()
                    if now >= refresh_at:
                        self._refresh()
                        refresh_at = now + (0.5 if self._owned_recording else 2)
                        if self._owned_recording:
                            try:
                                self._verify_scene()
                                self._verify_audio()
                            except ObsError:
                                self.stop_recording()
                                raise
                    self._tick_auto(time.monotonic())
                except ObsError as error:
                    self._state["error"] = str(error)
                    self.stop_auto()
                except Exception:
                    self._state["error"] = "OBS 后台任务失败，请检查连接后重试"
                    self._recording_uncertain = self._owned_recording
                    self._drop_client()
                    self.stop_auto()

    def disconnect(self):
        with self._lock:
            self._desired = False
            self.stop_auto()
            try:
                if self._owned_recording and self._client:
                    self.stop_recording()
                elif self._recording_directory_restore and self._client:
                    self._restore_recording_directory()
            finally:
                self._drop_client()
            return self.status()

    def close(self):
        self._shutdown.set()
        try:
            self.disconnect()
        except ObsError:
            pass
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout=5)
