from pathlib import Path

import pytest

from src.mvs.config import MvsAppConfig, MvsConfigStore


def test_config_round_trip(tmp_path: Path):
    store = MvsConfigStore(tmp_path / "camera.yaml")
    config = MvsAppConfig.from_dict(
        {
            "camera": {
                "ip": "192.168.1.20",
                "serial": "ABC123",
                "frame_timeout_ms": 800,
            },
            "capture": {
                "photo_dir": "photos",
                "video_dir": "videos",
                "photo_format": "png",
            },
            "server": {"host": "127.0.0.1", "port": 9000},
        }
    )

    store.save(config)

    assert store.load().to_dict() == config.to_dict()


def test_invalid_camera_ip_is_rejected():
    with pytest.raises(ValueError):
        MvsAppConfig.from_dict({"camera": {"ip": "192.168.999.2"}})
