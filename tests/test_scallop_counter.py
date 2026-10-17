from src.scallop_counter import LineCounter


def test_counts_one_forward_crossing_once():
    counter = LineCounter(((50, 0), (50, 100)), min_track_frames=3)
    assert not counter.update(7, (20, 30))
    assert not counter.update(7, (35, 30))
    assert counter.update(7, (60, 30))
    assert not counter.update(7, (75, 30))
    assert counter.count == 1


def test_ignores_reverse_crossing():
    counter = LineCounter(((50, 0), (50, 100)), min_track_frames=2)
    counter.update(2, (70, 30))
    counter.update(2, (60, 30))
    assert not counter.update(2, (40, 30))
    assert counter.count == 0


def test_ignores_crossing_outside_finite_line_segment():
    counter = LineCounter(((50, 20), (50, 80)), min_track_frames=2)
    counter.update(3, (30, 5))
    assert not counter.update(3, (60, 5))
    assert counter.count == 0


def test_deadband_prevents_jitter_from_counting():
    counter = LineCounter(((50, 0), (50, 100)), min_track_frames=2, deadband_px=5)
    counter.update(4, (40, 30))
    counter.update(4, (52, 30))
    assert counter.count == 0  # Still inside the deadband.
    assert counter.update(4, (60, 30))
    assert counter.count == 1


def test_reset_clears_count_and_track_history():
    counter = LineCounter(((50, 0), (50, 100)), min_track_frames=1)
    counter.update(5, (20, 30))
    counter.update(5, (60, 30))
    assert counter.count == 1
    counter.reset()
    assert counter.count == 0
    assert counter.update(5, (20, 30)) is False
