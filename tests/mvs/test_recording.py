import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.mvs.recording import VideoRecorder, fit_video_frame


def test_fit_video_frame_limits_large_images_and_keeps_even_dimensions():
    frame = np.zeros((7000, 7008, 3), dtype=np.uint8)

    resized = fit_video_frame(frame, max_width=1920, max_height=1080)

    height, width = resized.shape[:2]
    assert width <= 1920
    assert height <= 1080
    assert width % 2 == 0
    assert height % 2 == 0


def test_recorder_releases_writer_only_after_background_write_finishes(tmp_path: Path):
    write_started = threading.Event()
    allow_write = threading.Event()
    stop_finished = threading.Event()

    class BlockingWriter:
        def __init__(self):
            self.writing = False
            self.released_during_write = False
            self.released = False

        def isOpened(self):
            return True

        def write(self, frame):
            self.writing = True
            write_started.set()
            allow_write.wait(timeout=2.0)
            self.writing = False

        def release(self):
            self.released_during_write = self.writing
            self.released = True

    writer = BlockingWriter()
    recorder = VideoRecorder(writer_factory=lambda *args: writer)
    recorder.start(tmp_path / "test.mp4", video_format="mp4", fps=15.0)
    recorder.submit(np.zeros((48, 64, 3), dtype=np.uint8))
    assert write_started.wait(timeout=1.0)

    stopper = threading.Thread(
        target=lambda: (recorder.stop(), stop_finished.set()), daemon=True
    )
    stopper.start()
    time.sleep(0.05)

    assert not stop_finished.is_set()
    assert not writer.released

    allow_write.set()
    stopper.join(timeout=1.0)

    assert stop_finished.is_set()
    assert writer.released
    assert not writer.released_during_write


@pytest.mark.parametrize("video_format", ["avi", "mp4"])
def test_recorder_creates_readable_video(tmp_path: Path, video_format: str):
    path = tmp_path / f"readable.{video_format}"
    recorder = VideoRecorder()
    recorder.start(path, video_format=video_format, fps=10.0)
    for value in range(3):
        recorder.submit(np.full((48, 64, 3), value * 40, dtype=np.uint8))
        time.sleep(0.02)
    recorder.stop()

    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
        assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) >= 1
        ok, frame = capture.read()
        assert ok
        assert frame.shape == (48, 64, 3)
    finally:
        capture.release()
