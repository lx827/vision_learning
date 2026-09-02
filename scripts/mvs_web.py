"""启动 MVS 浏览器调试台。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from src.mvs.web import run

    parser = argparse.ArgumentParser(description="启动海康 MVS 相机浏览器调试台")
    parser.add_argument(
        "--config",
        default="configs/mvs/camera.yaml",
        help="调试台 YAML 配置路径",
    )
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
