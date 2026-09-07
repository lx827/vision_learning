from pathlib import Path

import pytest

from src.camera_console.config import CameraConfigStore, CameraConsoleConfig


def test_config_round_trip(tmp_path: Path):
    store = CameraConfigStore(tmp_path / "camera.yaml")
    config = CameraConsoleConfig.from_dict(
        {
            "camera": {
                "ip": "192.168.1.20",
                "serial": "ABC123",
                "frame_timeout_ms": 800,
            },
            "source_type": "droidcam_client",
            "droidcam_client": {
                "device_index": 2,
                "requested_width": 1920,
                "requested_height": 1080,
                "requested_fps": 30,
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
        CameraConsoleConfig.from_dict({"camera": {"ip": "192.168.999.2"}})


def test_invalid_video_size_is_rejected():
    with pytest.raises(ValueError, match="统一输出最大宽高"):
        CameraConsoleConfig.from_dict({"capture": {"output_max_width": 1}})


def test_invalid_droidcam_client_settings_are_rejected():
    with pytest.raises(ValueError, match="DroidCam 客户端摄像头编号"):
        CameraConsoleConfig.from_dict({"droidcam_client": {"device_index": -1}})


def test_legacy_opencv_config_is_migrated_to_droidcam_client():
    config = CameraConsoleConfig.from_dict(
        {"source_type": "opencv", "standard_camera": {"device_index": 3}}
    )

    assert config.source_type == "droidcam_client"
    assert config.droidcam_client.device_index == 3
    assert "standard_camera" not in config.to_dict()


def test_obs_droidcam_source_is_a_valid_peer_source():
    config = CameraConsoleConfig.from_dict(
        {
            "source_type": "obs_droidcam",
            "obs_droidcam": {"source_name": "DroidCam OBS", "photo_prefix": "phone"},
        }
    )

    assert config.source_type == "obs_droidcam"
    assert config.obs_droidcam.source_name == "DroidCam OBS"
    assert config.capture.photo_dir == "data/camera/photos"


def test_independent_bounds_are_migrated_to_one_output_size():
    config = CameraConsoleConfig.from_dict(
        {
            "capture": {
                "preview_max_width": 1280,
                "preview_max_height": 720,
                "photo_max_width": 1920,
                "photo_max_height": 1080,
                "video_max_width": 1920,
                "video_max_height": 1080,
            }
        }
    )

    assert config.capture.output_max_width == 1920
    assert config.capture.output_max_height == 1080
    assert "preview_max_width" not in config.to_dict()["capture"]
