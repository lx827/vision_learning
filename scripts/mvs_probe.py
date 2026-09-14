"""枚举并冒烟检查本机 MVS 相机。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from src.camera_console.config import CameraConfigStore
    from src.camera_console.service import FrameCameraService

    parser = argparse.ArgumentParser(description="检查 MVS SDK、设备连接和单帧采集")
    parser.add_argument("--config", default="configs/camera/camera.yaml")
    parser.add_argument(
        "--snapshot", action="store_true", help="成功取帧后保存一张测试照片"
    )
    args = parser.parse_args()

    service = FrameCameraService(CameraConfigStore(args.config))
    print(
        json.dumps(
            {"devices": service.enumerate_devices()}, ensure_ascii=False, indent=2
        )
    )
    try:
        service.connect()
        _, jpeg = service.wait_for_jpeg(0, timeout=5.0)
        if not jpeg:
            raise RuntimeError(f"连接后 5 秒内未收到预览帧：{service.status()}")
        result = {
            "status": service.status(),
            "parameters": service.get_parameters(),
        }
        if args.snapshot:
            result["snapshot"] = service.save_snapshot()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        service.disconnect()


if __name__ == "__main__":
    main()
