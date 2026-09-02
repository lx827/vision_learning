"""本机海康 MVS SDK 的薄适配层。

厂商 Python 封装从 MVS 安装目录动态加载，本仓库不复制或分发 SDK 文件。
"""

from __future__ import annotations

import copy
import importlib
import os
import sys
import threading
from ctypes import POINTER, byref, c_ubyte, cast, memset, sizeof
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np


class MvsError(RuntimeError):
    """MVS 调用链统一错误。"""


class MvsSdkUnavailableError(MvsError):
    """本机 MVS Python 封装不可用。"""


class MvsOperationError(MvsError):
    """包含 SDK 操作名和原始错误码的异常。"""

    def __init__(self, operation: str, code: int) -> None:
        self.operation = operation
        self.code = int(code) & 0xFFFFFFFF
        super().__init__(f"MVS {operation} 失败（0x{self.code:08X}）")


@dataclass(frozen=True)
class MvsDeviceInfo:
    index: int
    transport: str
    model: str
    serial: str
    user_name: str
    ip: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FloatFeature:
    value: float
    minimum: float
    maximum: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    number: int
    width: int
    height: int
    pixel_type: int
    lost_packets: int


_SDK_IMPORT_LOCK = threading.Lock()


def resolve_sdk_python_path(configured: str = "") -> Path:
    """解析官方 ``MvImport`` 目录。"""
    if configured.strip():
        path = Path(configured).expanduser()
    else:
        runtime = os.environ.get("MVCAM_COMMON_RUNENV", "").strip()
        if not runtime:
            raise MvsSdkUnavailableError(
                "未找到 MVCAM_COMMON_RUNENV；请先安装 MVS SDK，或在配置中填写 MvImport 路径"
            )
        path = Path(runtime) / "Samples" / "Python" / "MvImport"
    path = path.resolve()
    if not (path / "MvCameraControl_class.py").is_file():
        raise MvsSdkUnavailableError(f"MVS Python 封装目录无效：{path}")
    return path


def load_sdk(configured: str = "") -> ModuleType:
    """从本机安装目录动态导入官方 Python 封装。"""
    path = resolve_sdk_python_path(configured)
    with _SDK_IMPORT_LOCK:
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.insert(0, path_text)
        importlib.invalidate_caches()
        try:
            return importlib.import_module("MvCameraControl_class")
        except (ImportError, OSError) as exc:
            raise MvsSdkUnavailableError(f"无法加载 MVS SDK：{exc}") from exc


def _check(code: int, operation: str) -> None:
    if int(code) != 0:
        raise MvsOperationError(operation, int(code))


def _decode(value: object) -> str:
    raw = bytes(value).split(b"\0", 1)[0]
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _ip_text(value: int) -> str:
    return ".".join(str((int(value) >> shift) & 0xFF) for shift in (24, 16, 8, 0))


class MvsCamera:
    """MVS 相机生命周期、连续取流与 GenICam 参数访问。"""

    def __init__(self, sdk_python_path: str = "") -> None:
        self._sdk_python_path = sdk_python_path
        self._sdk: ModuleType | None = None
        self._camera = None
        self._device: MvsDeviceInfo | None = None
        self._initialized = False
        self._handle_created = False
        self._opened = False
        self._grabbing = False
        self._lock = threading.RLock()

    @staticmethod
    def enumerate_devices(sdk_python_path: str = "") -> list[MvsDeviceInfo]:
        sdk = load_sdk(sdk_python_path)
        _check(sdk.MvCamera.MV_CC_Initialize(), "初始化 SDK")
        try:
            return [item[0] for item in MvsCamera._enumerate_native(sdk)]
        finally:
            _check(sdk.MvCamera.MV_CC_Finalize(), "释放 SDK")

    @staticmethod
    def _enumerate_native(sdk: ModuleType) -> list[tuple[MvsDeviceInfo, object]]:
        device_list = sdk.MV_CC_DEVICE_INFO_LIST()
        layers = sdk.MV_GIGE_DEVICE | sdk.MV_USB_DEVICE
        _check(sdk.MvCamera.MV_CC_EnumDevices(layers, device_list), "枚举设备")
        devices: list[tuple[MvsDeviceInfo, object]] = []
        for index in range(int(device_list.nDeviceNum)):
            native = cast(
                device_list.pDeviceInfo[index], POINTER(sdk.MV_CC_DEVICE_INFO)
            ).contents
            native = copy.copy(native)
            if native.nTLayerType == sdk.MV_GIGE_DEVICE:
                info = native.SpecialInfo.stGigEInfo
                device = MvsDeviceInfo(
                    index=index,
                    transport="GigE",
                    model=_decode(info.chModelName),
                    serial=_decode(info.chSerialNumber),
                    user_name=_decode(info.chUserDefinedName),
                    ip=_ip_text(info.nCurrentIp),
                )
            else:
                info = native.SpecialInfo.stUsb3VInfo
                device = MvsDeviceInfo(
                    index=index,
                    transport="USB3",
                    model=_decode(info.chModelName),
                    serial=_decode(info.chSerialNumber),
                    user_name=_decode(info.chUserDefinedName),
                    ip="",
                )
            devices.append((device, native))
        return devices

    @property
    def device(self) -> MvsDeviceInfo | None:
        return self._device

    @property
    def is_connected(self) -> bool:
        camera = self._camera
        return bool(
            camera is not None and self._opened and camera.MV_CC_IsDeviceConnected()
        )

    def open(self, *, ip: str = "", serial: str = "") -> MvsDeviceInfo:
        with self._lock:
            if self.is_connected and self._device is not None:
                return self._device
            sdk = load_sdk(self._sdk_python_path)
            self._sdk = sdk
            try:
                _check(sdk.MvCamera.MV_CC_Initialize(), "初始化 SDK")
                self._initialized = True
                devices = self._enumerate_native(sdk)
                selected = self._select_device(devices, ip=ip, serial=serial)
                device, native = selected
                camera = sdk.MvCamera()
                self._camera = camera
                _check(camera.MV_CC_CreateHandle(native), "创建设备句柄")
                self._handle_created = True
                _check(camera.MV_CC_OpenDevice(sdk.MV_ACCESS_Exclusive, 0), "打开设备")
                self._opened = True
                if device.transport == "GigE":
                    packet_size = int(camera.MV_CC_GetOptimalPacketSize())
                    if 0 < packet_size < 0x80000000:
                        _check(
                            camera.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size),
                            "设置网络包大小",
                        )
                _check(
                    camera.MV_CC_SetEnumValue("TriggerMode", sdk.MV_TRIGGER_MODE_OFF),
                    "设置连续采集模式",
                )
                _check(camera.MV_CC_StartGrabbing(), "开始取流")
                self._grabbing = True
                self._device = device
                return device
            except Exception:
                self._cleanup(raise_errors=False)
                raise

    @staticmethod
    def _select_device(
        devices: list[tuple[MvsDeviceInfo, object]], *, ip: str, serial: str
    ) -> tuple[MvsDeviceInfo, object]:
        ip = ip.strip()
        serial = serial.strip()
        matches = [
            item
            for item in devices
            if (not ip or item[0].ip == ip) and (not serial or item[0].serial == serial)
        ]
        if not devices:
            raise MvsError("未发现 MVS 相机，请检查供电、网线和网卡地址")
        if not ip and not serial and len(devices) == 1:
            return devices[0]
        if not matches:
            selector = "、".join(
                value
                for value in (
                    f"IP={ip}" if ip else "",
                    f"序列号={serial}" if serial else "",
                )
                if value
            )
            raise MvsError(f"没有找到匹配的 MVS 相机（{selector or '未指定设备'}）")
        if len(matches) > 1:
            raise MvsError("设备条件匹配到多台相机，请填写 IP 或序列号")
        return matches[0]

    def get_frame(self, timeout_ms: int = 1000) -> Frame | None:
        with self._lock:
            if not self.is_connected or self._camera is None or self._sdk is None:
                raise MvsError("相机尚未连接")
            sdk = self._sdk
            frame = sdk.MV_FRAME_OUT()
            memset(byref(frame), 0, sizeof(frame))
            code = int(self._camera.MV_CC_GetImageBuffer(frame, int(timeout_ms)))
            if code != 0:
                if code == int(getattr(sdk, "MV_E_NODATA", -1)):
                    return None
                raise MvsOperationError("获取图像", code)
            if not frame.pBufAddr:
                return None
            try:
                info = frame.stFrameInfo
                width = int(info.nExtendWidth or info.nWidth)
                height = int(info.nExtendHeight or info.nHeight)
                image = self._convert_to_bgr(frame, width, height)
                return Frame(
                    image=image,
                    number=int(info.nFrameNum),
                    width=width,
                    height=height,
                    pixel_type=int(info.enPixelType),
                    lost_packets=int(info.nLostPacket),
                )
            finally:
                _check(self._camera.MV_CC_FreeImageBuffer(frame), "释放图像缓存")

    def _convert_to_bgr(self, frame: object, width: int, height: int) -> np.ndarray:
        sdk = self._sdk
        camera = self._camera
        if sdk is None or camera is None:
            raise MvsError("相机尚未连接")
        destination_size = width * height * 3
        destination = (c_ubyte * destination_size)()
        params = sdk.MV_CC_PIXEL_CONVERT_PARAM_EX()
        memset(byref(params), 0, sizeof(params))
        params.nWidth = width
        params.nHeight = height
        params.pSrcData = frame.pBufAddr
        params.nSrcDataLen = int(frame.stFrameInfo.nFrameLen)
        params.enSrcPixelType = frame.stFrameInfo.enPixelType
        params.enDstPixelType = sdk.PixelType_Gvsp_BGR8_Packed
        params.pDstBuffer = destination
        params.nDstBufferSize = destination_size
        _check(camera.MV_CC_ConvertPixelTypeEx(params), "转换 BGR 图像")
        return np.ctypeslib.as_array(destination).reshape(height, width, 3).copy()

    def get_parameters(self) -> dict[str, Any]:
        """读取当前设备支持的常用成像参数与范围。"""
        with self._lock:
            result: dict[str, Any] = {"capabilities": {}}
            for output_name, node in (
                ("exposure_us", "ExposureTime"),
                ("gain_db", "Gain"),
                ("frame_rate", "AcquisitionFrameRate"),
            ):
                try:
                    result[output_name] = self._get_float(node).to_dict()
                    result["capabilities"][output_name] = True
                except MvsOperationError:
                    result["capabilities"][output_name] = False
            for output_name, node in (
                ("exposure_mode", "ExposureAuto"),
                ("gain_mode", "GainAuto"),
                ("white_balance_mode", "BalanceWhiteAuto"),
            ):
                try:
                    result[output_name] = self._get_enum(node)
                    result["capabilities"][output_name] = True
                except MvsOperationError:
                    result["capabilities"][output_name] = False
            try:
                result["frame_rate_enabled"] = self._get_bool(
                    "AcquisitionFrameRateEnable"
                )
                result["capabilities"]["frame_rate_enabled"] = True
            except MvsOperationError:
                result["capabilities"]["frame_rate_enabled"] = False
            return result

    def apply_parameters(self, values: dict[str, Any]) -> dict[str, Any]:
        """应用白名单内的 GenICam 成像参数。"""
        with self._lock:
            if "exposure_mode" in values:
                self._set_mode("ExposureAuto", values["exposure_mode"])
            if "exposure_us" in values and values.get("exposure_mode", "off") == "off":
                self._set_float("ExposureTime", values["exposure_us"])
            if "gain_mode" in values:
                self._set_mode("GainAuto", values["gain_mode"])
            if "gain_db" in values and values.get("gain_mode", "off") == "off":
                self._set_float("Gain", values["gain_db"])
            if "frame_rate_enabled" in values:
                self._set_bool(
                    "AcquisitionFrameRateEnable", values["frame_rate_enabled"]
                )
            if "frame_rate" in values and values.get("frame_rate_enabled", True):
                self._set_float("AcquisitionFrameRate", values["frame_rate"])
            if "white_balance_mode" in values:
                self._set_mode("BalanceWhiteAuto", values["white_balance_mode"])
            return self.get_parameters()

    def _get_float(self, node: str) -> FloatFeature:
        sdk, camera = self._require_open()
        value = sdk.MVCC_FLOATVALUE()
        memset(byref(value), 0, sizeof(value))
        _check(camera.MV_CC_GetFloatValue(node, value), f"读取 {node}")
        return FloatFeature(
            float(value.fCurValue), float(value.fMin), float(value.fMax)
        )

    def _set_float(self, node: str, value: Any) -> None:
        _, camera = self._require_open()
        _check(camera.MV_CC_SetFloatValue(node, float(value)), f"设置 {node}")

    def _get_enum(self, node: str) -> str:
        sdk, camera = self._require_open()
        value = sdk.MVCC_ENUMVALUE()
        memset(byref(value), 0, sizeof(value))
        _check(camera.MV_CC_GetEnumValue(node, value), f"读取 {node}")
        return {0: "off", 1: "once", 2: "continuous"}.get(
            int(value.nCurValue), str(int(value.nCurValue))
        )

    def _set_mode(self, node: str, mode: Any) -> None:
        _, camera = self._require_open()
        normalized = str(mode).strip().lower()
        names = {"off": "Off", "once": "Once", "continuous": "Continuous"}
        if normalized not in names:
            raise ValueError(f"{node} 模式必须是 off、once 或 continuous")
        _check(
            camera.MV_CC_SetEnumValueByString(node, names[normalized]), f"设置 {node}"
        )

    def _get_bool(self, node: str) -> bool:
        _, camera = self._require_open()
        from ctypes import c_bool

        value = c_bool(False)
        _check(camera.MV_CC_GetBoolValue(node, value), f"读取 {node}")
        return bool(value.value)

    def _set_bool(self, node: str, value: Any) -> None:
        _, camera = self._require_open()
        _check(camera.MV_CC_SetBoolValue(node, bool(value)), f"设置 {node}")

    def _require_open(self) -> tuple[ModuleType, object]:
        if not self.is_connected or self._sdk is None or self._camera is None:
            raise MvsError("相机尚未连接")
        return self._sdk, self._camera

    def close(self) -> None:
        with self._lock:
            self._cleanup(raise_errors=True)

    def _cleanup(self, *, raise_errors: bool) -> None:
        errors: list[MvsError] = []

        def call(operation: str, callback) -> None:
            try:
                code = int(callback())
                if code != 0:
                    errors.append(MvsOperationError(operation, code))
            except Exception as exc:
                errors.append(MvsError(f"MVS {operation} 清理失败：{exc}"))

        if self._camera is not None and self._grabbing:
            call("停止取流", self._camera.MV_CC_StopGrabbing)
        self._grabbing = False
        if self._camera is not None and self._opened:
            call("关闭设备", self._camera.MV_CC_CloseDevice)
        self._opened = False
        if self._camera is not None and self._handle_created:
            call("销毁句柄", self._camera.MV_CC_DestroyHandle)
        self._handle_created = False
        self._camera = None
        self._device = None
        if self._sdk is not None and self._initialized:
            call("释放 SDK", self._sdk.MvCamera.MV_CC_Finalize)
        self._initialized = False
        self._sdk = None
        if raise_errors and errors:
            raise errors[0]


__all__ = [
    "FloatFeature",
    "Frame",
    "MvsCamera",
    "MvsDeviceInfo",
    "MvsError",
    "MvsOperationError",
    "MvsSdkUnavailableError",
    "load_sdk",
    "resolve_sdk_python_path",
]
