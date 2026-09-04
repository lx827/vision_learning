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
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="启动服务但不自动打开浏览器",
    )
    args = parser.parse_args()
    run(args.config, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
