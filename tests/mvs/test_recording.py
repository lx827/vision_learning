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
    time.sleep(0.08)
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


def test_recording_duration_tracks_wall_clock_when_input_fps_is_low(tmp_path: Path):
    class CountingWriter:
        def __init__(self):
            self.frames_written = 0

        def isOpened(self):
            return True

        def write(self, frame):
            self.frames_written += 1

        def release(self):
            pass

    writer = CountingWriter()
    fps = 20.0
    clock_value = [0.0]
    recorder = VideoRecorder(
        writer_factory=lambda *args: writer,
        clock=lambda: clock_value[0],
    )
    recorder.start(tmp_path / "realtime.mp4", video_format="mp4", fps=fps)
    recorder.submit(np.zeros((48, 64, 3), dtype=np.uint8))
    deadline = time.monotonic() + 1.0
    while recorder.output_size == (0, 0) and time.monotonic() < deadline:
        time.sleep(0.001)
    assert recorder.output_size == (64, 48)

    for second in range(1, 5):
        clock_value[0] = float(second)
        recorder.submit(np.zeros((48, 64, 3), dtype=np.uint8))
    clock_value[0] = 5.0
    recorder.stop()

    encoded_duration = writer.frames_written / fps
    assert encoded_duration == pytest.approx(5.0, abs=1 / fps)
    assert recorder.duplicated_frames > 0


def test_recording_duration_starts_before_first_camera_frame(tmp_path: Path):
    class CountingWriter:
        def __init__(self):
            self.frames_written = 0

        def isOpened(self):
            return True

        def write(self, frame):
            self.frames_written += 1

        def release(self):
            pass

    writer = CountingWriter()
    clock_value = [0.0]
    recorder = VideoRecorder(
        writer_factory=lambda *args: writer,
        clock=lambda: clock_value[0],
    )
    recorder.start(tmp_path / "delayed-first-frame.mp4", video_format="mp4", fps=10.0)
    clock_value[0] = 2.0
    recorder.submit(np.zeros((48, 64, 3), dtype=np.uint8))
    clock_value[0] = 5.0
    recorder.stop()

    assert writer.frames_written / 10.0 == pytest.approx(5.0, abs=0.1)


@pytest.mark.parametrize("video_format", ["avi", "mp4"])
def test_recorder_creates_readable_video(tmp_path: Path, video_format: str):
    path = tmp_path / f"readable.{video_format}"
    clock_value = [0.0]
    recorder = VideoRecorder(clock=lambda: clock_value[0])
    recorder.start(path, video_format=video_format, fps=10.0)
    for value, captured_at in enumerate((0.0, 0.5)):
        clock_value[0] = captured_at
        recorder.submit(np.full((48, 64, 3), value * 40, dtype=np.uint8))
        deadline = time.monotonic() + 1.0
        while recorder.output_size == (0, 0) and time.monotonic() < deadline:
            time.sleep(0.001)
    clock_value[0] = 1.0
    recorder.stop()

    capture = cv2.VideoCapture(str(path))
    try:
        assert capture.isOpened()
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        file_fps = capture.get(cv2.CAP_PROP_FPS)
        assert frame_count == 10
        assert file_fps == pytest.approx(10.0)
        assert frame_count / file_fps == pytest.approx(1.0, abs=0.1)
        ok, frame = capture.read()
        assert ok
        assert frame.shape == (48, 64, 3)
    finally:
        capture.release()
