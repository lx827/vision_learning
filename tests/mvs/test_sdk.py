from ctypes import Structure, c_int, c_int64, c_uint
from types import SimpleNamespace

import pytest

from src.mvs.sdk import MvsCamera


@pytest.mark.parametrize(
    ("access_mode", "expected"),
    [(0, False), (1, False), (2, True), (3, False), (4, True)],
)
def test_node_capability_requires_write_access(access_mode: int, expected: bool):
    class FakeNativeCamera:
        def MV_CC_IsDeviceConnected(self):
            return True

        def MV_XML_GetNodeAccessMode(self, node, output):
            output.value = access_mode
            return 0

    camera = MvsCamera()
    camera._sdk = SimpleNamespace(MV_XML_AccessMode=c_int, AM_WO=2, AM_RW=4)
    camera._camera = FakeNativeCamera()
    camera._opened = True

    assert camera._is_writable("Gain") is expected


def test_apply_roi_stops_stream_centers_offsets_and_restarts():
    class IntValue(Structure):
        _fields_ = [
            ("nCurValue", c_int64),
            ("nMax", c_int64),
            ("nMin", c_int64),
            ("nInc", c_int64),
            ("nReserved", c_uint * 16),
        ]

    class FakeNativeCamera:
        def __init__(self):
            self.values = {"Width": 7008, "Height": 7000, "OffsetX": 0, "OffsetY": 0}
            self.calls = []

        def MV_CC_IsDeviceConnected(self):
            return True

        def MV_XML_GetNodeAccessMode(self, node, output):
            output.value = 4
            return 0

        def MV_CC_GetIntValueEx(self, node, output):
            limits = {
                "Width": (64, 7008, 8),
                "Height": (64, 7000, 8),
                "OffsetX": (0, 7008 - self.values["Width"], 8),
                "OffsetY": (0, 7000 - self.values["Height"], 8),
            }
            minimum, maximum, increment = limits[node]
            output.nCurValue = self.values[node]
            output.nMin = minimum
            output.nMax = maximum
            output.nInc = increment
            return 0

        def MV_CC_SetIntValueEx(self, node, value):
            self.calls.append(("set", node, value))
            self.values[node] = value
            return 0

        def MV_CC_StopGrabbing(self):
            self.calls.append(("stop",))
            return 0

        def MV_CC_StartGrabbing(self):
            self.calls.append(("start",))
            return 0

    native = FakeNativeCamera()
    camera = MvsCamera()
    camera._sdk = SimpleNamespace(
        MVCC_INTVALUE_EX=IntValue,
        MV_XML_AccessMode=c_int,
        AM_WO=2,
        AM_RW=4,
    )
    camera._camera = native
    camera._opened = True
    camera._grabbing = True
    camera.get_parameters = lambda: {"width": native.values["Width"]}

    result = camera.apply_roi({"width": 2000, "height": 2000, "centered": True})

    assert result == {"width": 2000}
    assert native.values == {
        "Width": 2000,
        "Height": 2000,
        "OffsetX": 2504,
        "OffsetY": 2496,
    }
    assert native.calls[0] == ("stop",)
    assert native.calls[-1] == ("start",)
