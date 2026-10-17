"""capturecore 1.x C ABI 绑定；采集、判稳拍照和录像均由原生内核执行。

不注册 Python 帧回调，避免 Python 处理阻塞内核捕获线程。
仅按需拷贝最新帧用于预览；会话关闭须由宿主与取帧操作串行管理。
"""

from __future__ import annotations

import ctypes as ct
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIXEL_FORMATS = {0: "MJPEG", 1: "YUYV", 2: "NV12", 3: "RGB24", 4: "BGRA"}


class CaptureError(RuntimeError):
    """可呈现给用户的内核、设备或文件错误。"""


class DeviceInfo(ct.Structure):
    _fields_ = [
        ("index", ct.c_uint32),
        ("name", ct.c_char * 128),
        ("device_id", ct.c_char * 260),
        ("usb_vid", ct.c_uint32),
        ("usb_pid", ct.c_uint32),
    ]


class Format(ct.Structure):
    _fields_ = [
        ("width", ct.c_uint32),
        ("height", ct.c_uint32),
        ("fps", ct.c_uint32),
        ("format", ct.c_int),
    ]


class Frame(ct.Structure):
    _fields_ = [
        ("timestamp_100ns", ct.c_uint64),
        ("sequence", ct.c_uint64),
        ("width", ct.c_uint32),
        ("height", ct.c_uint32),
        ("format", ct.c_int),
        ("data", ct.c_void_p),
        ("size", ct.c_size_t),
    ]


class Stats(ct.Structure):
    _fields_ = [
        ("frames_delivered", ct.c_uint64),
        ("bytes_delivered", ct.c_uint64),
        ("measured_fps", ct.c_double),
    ]


class PropOption(ct.Structure):
    _fields_ = [("value", ct.c_int32), ("name", ct.c_char * 32)]


class PropMeta(ct.Structure):
    _fields_ = [
        ("struct_size", ct.c_uint32),
        ("id", ct.c_uint32),
        ("name", ct.c_char * 48),
        ("type", ct.c_int),
        ("min", ct.c_int64),
        ("max", ct.c_int64),
        ("step", ct.c_int64),
        ("def", ct.c_int64),
        ("current", ct.c_int64),
        ("current_is_auto", ct.c_int32),
        ("flags", ct.c_uint32),
        ("option_count", ct.c_uint32),
        ("options", PropOption * 16),
        ("unit", ct.c_uint32),
    ]


class RecordConfig(ct.Structure):
    _fields_ = [
        ("struct_size", ct.c_uint32),
        ("codec", ct.c_int),
        ("container", ct.c_int),
        ("bitrate_kbps", ct.c_uint32),
        ("segment_secs", ct.c_uint32),
        ("gop_secs", ct.c_uint32),
        ("reserved", ct.c_uint32 * 4),
    ]


class RecordResult(ct.Structure):
    _fields_ = [
        ("frames_written", ct.c_uint64),
        ("bytes_written", ct.c_uint64),
        ("segments", ct.c_uint32),
        ("last_path", ct.c_char * 260),
        ("encoder", ct.c_char * 32),
    ]


def _text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    timestamp_100ns: int
    width: int
    height: int
    pixel_format: int
    data: bytes


def decode_frame(frame: CapturedFrame) -> np.ndarray:
    """按 ABI 的紧密像素布局转 BGR；MJPEG 原样预览时不调用此函数。"""
    raw = np.frombuffer(frame.data, dtype=np.uint8)
    width, height, fmt = frame.width, frame.height, frame.pixel_format
    if width <= 0 or height <= 0:
        raise CaptureError("Capture 帧尺寸无效")
    if fmt == 0:
        image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if image is None:
            raise CaptureError("Capture MJPEG 帧解码失败")
        return image
    try:
        if fmt == 1:
            return cv2.cvtColor(
                raw[: width * height * 2].reshape(height, width, 2),
                cv2.COLOR_YUV2BGR_YUY2,
            )
        if fmt == 2:
            return cv2.cvtColor(
                raw[: width * height * 3 // 2].reshape(height * 3 // 2, width),
                cv2.COLOR_YUV2BGR_NV12,
            )
        if fmt == 3:
            return cv2.cvtColor(
                raw[: width * height * 3].reshape(height, width, 3), cv2.COLOR_RGB2BGR
            )
        if fmt == 4:
            return cv2.cvtColor(
                raw[: width * height * 4].reshape(height, width, 4), cv2.COLOR_BGRA2BGR
            )
    except (ValueError, cv2.error) as exc:
        raise CaptureError("Capture 原始帧数据不完整或像素布局无效") from exc
    raise CaptureError(f"不支持的 Capture 像素格式：{fmt}")


class CaptureCore:
    """按完整路径加载内核，持有依赖搜索目录，直到宿主退出。"""

    def __init__(self, library_path: str):
        path = Path(library_path).expanduser()
        self.path = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
        if not self.path.is_file():
            raise CaptureError(
                f"找不到 Capture 内核：{self.path}；请先构建 capture 项目或修改内核路径"
            )
        self._dll_directory = None
        try:
            if os.name == "nt":
                self._dll_directory = os.add_dll_directory(str(self.path.parent))
            self.dll = ct.CDLL(str(self.path))
            self._bind()
            version = self.dll.cap_abi_version()
            if version >> 16 != 1:
                raise CaptureError(
                    f"Capture 内核 ABI 不兼容：需要 1.x，实际 {version >> 16}.{version & 65535}"
                )
        except (OSError, AttributeError) as exc:
            raise CaptureError(
                f"Capture 内核加载失败：{exc}；请确保同目录依赖 DLL 完整且与 Python 位数一致"
            ) from exc

    def _bind(self) -> None:
        def bind(name, result, *args):
            fn = getattr(self.dll, name)
            fn.restype, fn.argtypes = result, list(args)

        ptr = ct.c_void_p
        bind("cap_abi_version", ct.c_uint32)
        bind("cap_last_error", ct.c_char_p)
        bind("cap_result_string", ct.c_char_p, ct.c_int)
        bind(
            "cap_device_list", ct.c_int, ct.POINTER(DeviceInfo), ct.POINTER(ct.c_uint32)
        )
        bind("cap_open", ct.c_int, ct.c_char_p, ct.POINTER(ptr))
        bind("cap_close", ct.c_int, ptr)
        bind(
            "cap_format_list",
            ct.c_int,
            ptr,
            ct.POINTER(Format),
            ct.POINTER(ct.c_uint32),
        )
        bind("cap_select_format", ct.c_int, ptr, ct.c_uint32)
        bind("cap_start", ct.c_int, ptr, ptr, ptr)
        bind("cap_grab_latest", ct.c_int, ptr, ptr, ct.c_size_t, ct.POINTER(Frame))
        bind("cap_stats_get", Stats, ptr)
        bind("cap_snapshot", ct.c_int, ptr, ct.c_char_p, ct.c_uint32)
        bind("cap_record_start", ct.c_int, ptr, ct.c_char_p, ct.POINTER(RecordConfig))
        bind("cap_record_stop", ct.c_int, ptr, ct.POINTER(RecordResult))
        bind("cap_recording", ct.c_int32, ptr)
        bind(
            "cap_prop_list",
            ct.c_int,
            ptr,
            ct.POINTER(PropMeta),
            ct.POINTER(ct.c_uint32),
        )
        bind(
            "cap_prop_get",
            ct.c_int,
            ptr,
            ct.c_uint32,
            ct.POINTER(ct.c_int64),
            ct.POINTER(ct.c_int32),
        )
        bind("cap_prop_set", ct.c_int, ptr, ct.c_uint32, ct.c_int64)
        bind("cap_prop_set_auto", ct.c_int, ptr, ct.c_uint32, ct.c_int32)

    def check(self, code: int) -> None:
        if code != 0:
            reason = _text(self.dll.cap_result_string(code))
            detail = _text(self.dll.cap_last_error())
            # Media Foundation reports E_ACCESSDENIED for an already-open UVC
            # device. The native API currently labels this open-path error as
            # internal, so expose the actionable diagnosis to the web client.
            if "backend code -2147024891" in detail or "backend code 0x80070005" in detail:
                reason = "device busy or access denied"
                detail = f"{detail}；请先关闭 capture.exe、相机应用、OBS/MVS 等占用相机的程序，并检查 Windows 相机权限"
            raise CaptureError(f"Capture：{reason}（{detail}）")

    def devices(self) -> list[dict]:
        count = ct.c_uint32()
        self.check(self.dll.cap_device_list(None, ct.byref(count)))
        # 允许枚举两步之间插入设备，最多重试三次。
        for _ in range(3):
            array = (DeviceInfo * count.value)()
            code = self.dll.cap_device_list(array, ct.byref(count))
            if code != 2:
                self.check(code)
                return [
                    {
                        "index": d.index,
                        "model": _text(d.name),
                        "device_id": _text(d.device_id),
                        "serial": _text(d.device_id),
                        "usb_vid": d.usb_vid,
                        "usb_pid": d.usb_pid,
                        "ip": "",
                        "transport": "Capture/UVC",
                        "user_name": f"USB {d.usb_vid:04X}:{d.usb_pid:04X}",
                    }
                    for d in array[: count.value]
                ]
            self.check(self.dll.cap_device_list(None, ct.byref(count)))
        raise CaptureError("设备列表持续变化，请重新刷新")

    def open(self, device_id: str) -> "CaptureCamera":
        handle = ct.c_void_p()
        self.check(self.dll.cap_open(device_id.encode("utf-8"), ct.byref(handle)))
        return CaptureCamera(self, handle)


class CaptureCamera:
    def __init__(self, core: CaptureCore, handle: ct.c_void_p):
        self.core, self.handle = core, handle
        self._buffer = None

    def properties(self) -> list[dict]:
        """每次现查能力、运行态和现值，避免将默认值误当成相机读数。"""
        dll = self.core.dll
        count = ct.c_uint32()
        code = dll.cap_prop_list(self.handle, None, ct.byref(count))
        if code == 5:  # CAP_ERR_UNSUPPORTED：设备没有属性通道。
            return []
        self.core.check(code)
        for _ in range(3):
            array = (PropMeta * count.value)()
            for meta in array:
                meta.struct_size = ct.sizeof(PropMeta)
            code = dll.cap_prop_list(self.handle, array, ct.byref(count))
            if code == 2:
                continue
            self.core.check(code)
            result = []
            for meta in array[: count.value]:
                value, automatic = ct.c_int64(), ct.c_int32()
                self.core.check(
                    dll.cap_prop_get(
                        self.handle, meta.id, ct.byref(value), ct.byref(automatic)
                    )
                )
                result.append(
                    {
                        "id": meta.id,
                        "name": _text(meta.name),
                        "type": meta.type,
                        "minimum": meta.min,
                        "maximum": meta.max,
                        "step": meta.step,
                        "default": getattr(meta, "def"),
                        "value": value.value,
                        "is_auto": bool(automatic.value),
                        "flags": meta.flags,
                        "unit": meta.unit,
                        "options": [
                            {"value": option.value, "name": _text(option.name)}
                            for option in meta.options[: min(meta.option_count, 16)]
                        ],
                    }
                )
            return result
        raise CaptureError("成像参数能力发生变化，请刷新参数后重试")

    def set_property(self, property_id: int, value: int, *, boolean=False) -> None:
        code = self.core.dll.cap_prop_set(self.handle, property_id, value)
        # 与官方前端相同：某些 Windows 布尔项需通过自动模式接口写入。
        if boolean and code in (1, 5):
            code = self.core.dll.cap_prop_set_auto(self.handle, property_id, value)
        self.core.check(code)

    def formats(self) -> list[dict]:
        count = ct.c_uint32()
        dll = self.core.dll
        self.core.check(dll.cap_format_list(self.handle, None, ct.byref(count)))
        array = (Format * count.value)()
        self.core.check(dll.cap_format_list(self.handle, array, ct.byref(count)))
        return [
            {
                "index": i,
                "width": f.width,
                "height": f.height,
                "fps": f.fps,
                "pixel_format": f.format,
                "name": PIXEL_FORMATS.get(f.format, "未知"),
            }
            for i, f in enumerate(array[: count.value])
        ]

    def start(self, format_index: int) -> None:
        if format_index >= 0:
            self.core.check(self.core.dll.cap_select_format(self.handle, format_index))
        self.core.check(self.core.dll.cap_start(self.handle, None, None))

    def latest_frame(self, after: int | None = None) -> CapturedFrame | None:
        frame = Frame()
        if after is not None:
            code = self.core.dll.cap_grab_latest(self.handle, None, 0, ct.byref(frame))
            if code == 8:
                return None
            if code != 2:
                self.core.check(code)
            if frame.sequence == after:
                return None  # 只有元数据查询，不拷贝重复的图像字节。
            if self._buffer is None or len(self._buffer) < frame.size:
                self._buffer = ct.create_string_buffer(frame.size)
        for _ in range(3):
            capacity = len(self._buffer) if self._buffer is not None else 0
            code = self.core.dll.cap_grab_latest(
                self.handle, self._buffer, capacity, ct.byref(frame)
            )
            if code == 8:  # CAP_ERR_NOT_RUNNING：首帧尚未到达。
                return None
            if code == 2:
                self._buffer = ct.create_string_buffer(frame.size)
                continue
            self.core.check(code)
            return CapturedFrame(
                frame.sequence,
                frame.timestamp_100ns,
                frame.width,
                frame.height,
                frame.format,
                ct.string_at(frame.data, frame.size),
            )
        return None  # 可变大小 MJPEG 恰好连续增长；下一轮取最新帧。

    def stats(self) -> Stats:
        return self.core.dll.cap_stats_get(self.handle)

    def snapshot(self, path: Path) -> None:
        self.core.check(
            self.core.dll.cap_snapshot(self.handle, str(path).encode("utf-8"), 2000)
        )
        if not path.is_file() or path.stat().st_size == 0:
            raise CaptureError("Capture 未生成有效快照文件")

    def start_recording(self, path: Path, *, mjpeg: bool) -> None:
        config = RecordConfig()
        config.struct_size = ct.sizeof(config)
        config.codec, config.container = (0, 1) if mjpeg else (1, 2)
        self.core.check(
            self.core.dll.cap_record_start(
                self.handle, str(path).encode("utf-8"), ct.byref(config)
            )
        )

    def stop_recording(self) -> dict:
        result = RecordResult()
        self.core.check(self.core.dll.cap_record_stop(self.handle, ct.byref(result)))
        return {
            "frames_written": result.frames_written,
            "bytes_written": result.bytes_written,
            "encoder": _text(result.encoder),
            "last_path": _text(result.last_path),
        }

    def close(self) -> None:
        if self.handle:
            handle, self.handle = self.handle, None
            self.core.check(self.core.dll.cap_close(handle))
