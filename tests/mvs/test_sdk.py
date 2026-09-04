from ctypes import c_int
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
