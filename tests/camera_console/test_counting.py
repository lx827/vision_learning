"""Exercise reset through the running inference worker, without camera hardware."""

import queue
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from src.camera_console.counting import CountingService


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def int(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class FakeBoxes(SimpleNamespace):
    def __len__(self):
        return len(self.conf.values)


@pytest.fixture
def worker(tmp_path, monkeypatch, request):
    frames = queue.Queue()
    inference_entered = threading.Event()
    inference_release = threading.Event()
    inference_release.set()
    config = tmp_path / "count.yaml"
    weights = tmp_path / "fake.pt"
    weights.touch()
    config.write_text(
        f"model:\n  weights: {weights.as_posix()}\n"
        "tracking:\n  min_track_frames: 1\n"
        "roi:\n  width: 100\n  height: 100\n"
        "count_line:\n  start: [50, 0]\n  end: [50, 100]\n"
        "  direction: positive_to_negative\n",
        encoding="utf-8",
    )

    class Camera:
        def status(self):
            return {"connected": True}

        def latest_image(self, after):
            try:
                return frames.get(timeout=0.05)
            except queue.Empty:
                return None

    class Model:
        def __init__(self):
            self.shapes = []

        def track(self, frame, **kwargs):
            self.shapes.append(frame.shape)
            inference_entered.set()
            assert inference_release.wait(3), "inference was not released"
            track_id, center_x = (int(v) for v in frame[0, 0, :2])
            boxes = FakeBoxes(
                id=FakeTensor([track_id]) if track_id != 255 else None,
                xyxy=FakeTensor([[center_x - 3, 27, center_x + 3, 33]]),
                conf=FakeTensor([0.9]),
            )
            return [SimpleNamespace(boxes=boxes)]

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda _: Model()))
    service = CountingService(lambda: Camera(), config)
    service._config.update(getattr(request, "param", {}))
    service.start()

    def send(track_id, center_x, sequence, *, wait=True):
        inference_entered.clear()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[0, 0, :2] = [track_id, center_x]
        frames.put((sequence, frame))
        if wait:
            with service._condition:
                assert service._condition.wait_for(
                    lambda: service.status["frame_sequence"] == sequence
                    or service.status["error"],
                    timeout=3,
                ), "worker did not publish frame"
            assert not service.status["error"]

    yield service, send, inference_entered, inference_release
    inference_release.set()
    service.stop()


def test_reset_stays_zero_then_counts_next_new_crossing_from_one(worker):
    service, send, _, _ = worker
    send(1, 20, 1)
    send(1, 60, 2)
    send(2, 20, 3)
    send(2, 60, 4)
    assert service.status["count"] == 2

    assert service.reset()["count"] == 0
    send(2, 70, 5)
    assert service.status["count"] == 0
    send(3, 20, 6)
    send(3, 60, 7)
    assert service.status["count"] == 1
    # Previously counted tracks must not be counted twice after clearing.
    send(1, 20, 8)
    send(1, 60, 9)
    assert service.status["count"] == 1


def test_reset_during_inference_does_not_publish_old_count_or_frame(worker):
    service, send, entered, release = worker
    send(1, 20, 1)
    send(1, 60, 2)
    release.clear()
    send(1, 70, 3, wait=False)
    assert entered.wait(3)
    service.reset()
    release.set()
    send(2, 20, 4)
    send(2, 60, 5)
    assert service.status["count"] == 1


def test_reset_discards_previous_preview_without_rewinding_sequence(worker):
    service, send, _, _ = worker
    send(1, 20, 1)
    sequence = service.status["frame_sequence"]
    service.reset()
    assert service.status["frame_sequence"] == sequence
    assert service.wait_for_frame(sequence, timeout=0)[1] is None


@pytest.mark.parametrize("worker", [{
    "count_mode": "roi", "roi": {"x": 40, "y": 10, "width": 40, "height": 50},
    "min_track_frames": 99,
}], indirect=True)
def test_roi_worker_counts_on_first_tracked_center_and_reset_keeps_ids(worker):
    service, send, _, _ = worker
    send(1, 30, 1)
    assert service.status["count"] == 0
    send(1, 50, 2)
    assert service.status["count"] == 1
    send(1, 60, 3)
    assert service.status["count"] == 1
    service.reset()
    send(1, 65, 4)
    assert service.status["count"] == 0
    send(2, 50, 5)
    assert service.status["count"] == 1
    assert service._model.shapes[-1] == (100, 100, 3)


def test_restart_reuses_model_but_starts_new_counting_session(worker):
    service, send, _, _ = worker
    send(1, 20, 1)
    send(1, 60, 2)
    assert service.status["count"] == 1
    model = service._model
    service.stop()
    service.start()
    send(2, 20, 3)
    assert service._model is model
    assert service.status["count"] == 0
    send(2, 60, 4)
    assert service.status["count"] == 1


@pytest.mark.parametrize("worker", [{"count_mode": "roi"}], indirect=True)
def test_untracked_detection_is_visible_but_not_counted(worker):
    service, send, _, _ = worker
    send(255, 50, 1)
    assert service.status["detections"] == 1
    assert service.status["count"] == 0
    send(1, 50, 2)
    assert service.status["count"] == 1


def test_prepare_is_nonblocking_and_does_not_touch_camera(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    loads = []

    class Model:
        def track(self, frame, **kwargs):
            entered.set()
            assert release.wait(3)

    def load(weights):
        loads.append(weights)
        return Model()

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=load))
    weights = tmp_path / "fake.pt"
    weights.touch()
    config = tmp_path / "count.yaml"
    config.write_text(f"model:\n  weights: {weights.as_posix()}\n", encoding="utf-8")

    def forbidden_camera():
        pytest.fail("Warmup must not acquire the camera")

    service = CountingService(forbidden_camera, config)
    try:
        assert service.prepare()["active"] is False
        assert entered.wait(3)
        assert service.status["preparing"] is True
        service.prepare()
        release.set()
        service._prepare_thread.join(3)
        service.prepare()
        service._prepare_thread.join(3)
        assert len(loads) == 1
        assert service.status["model_ready"] is True
    finally:
        release.set()
        service.stop()
