"""Small, deterministic line-crossing counter for tracked detections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Detection:
    track_id: int
    box: tuple[float, float, float, float]
    confidence: float


class LineCounter:
    """Count each track once when its box center crosses a finite line."""

    def __init__(
        self,
        line: tuple[tuple[float, float], tuple[float, float]],
        *,
        direction: str = "positive_to_negative",
        min_track_frames: int = 3,
        deadband_px: float = 3.0,
    ) -> None:
        if direction not in {"positive_to_negative", "negative_to_positive"}:
            raise ValueError("direction must be positive_to_negative or negative_to_positive")
        if min_track_frames < 1 or deadband_px < 0:
            raise ValueError("min_track_frames must be positive and deadband_px non-negative")
        (self.x1, self.y1), (self.x2, self.y2) = line
        self._length = ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5
        if self._length == 0:
            raise ValueError("counting line endpoints must differ")
        self.direction = direction
        self.min_track_frames = min_track_frames
        self.deadband_px = deadband_px
        self.count = 0
        self.counted_ids: set[int] = set()
        self._states: dict[int, dict[str, object]] = {}

    def reset(self) -> None:
        """Reset the accumulated count and all track history."""
        self.count = 0
        self.counted_ids.clear()
        self._states.clear()

    def update(self, track_id: int, point: tuple[float, float]) -> bool:
        """Record a track point and return True only for a new valid crossing."""
        x, y = point
        state = self._states.setdefault(track_id, {"frames": 0, "side": 0, "point": None})
        state["frames"] = int(state["frames"]) + 1
        distance = ((self.x2 - self.x1) * (y - self.y1) - (self.y2 - self.y1) * (x - self.x1)) / self._length
        side = 1 if distance > self.deadband_px else -1 if distance < -self.deadband_px else 0
        previous_side = int(state["side"])
        previous_point = state["point"]
        counted = False
        if (
            track_id not in self.counted_ids
            and int(state["frames"]) >= self.min_track_frames
            and previous_side != 0
            and side != 0
            and previous_side != side
            and previous_point is not None
            and self._crosses_segment(previous_point, (x, y))
            and self._matches_direction(previous_side, side)
        ):
            self.count += 1
            self.counted_ids.add(track_id)
            counted = True
        if side:
            state["side"] = side
        # Keep the last point outside the deadband so jitter near the line
        # cannot erase the evidence of a real crossing.
        if side:
            state["point"] = (x, y)
        return counted

    def _matches_direction(self, previous: int, current: int) -> bool:
        if self.direction == "positive_to_negative":
            return previous > 0 and current < 0
        return previous < 0 and current > 0

    def _crosses_segment(
        self, start: tuple[float, float], end: tuple[float, float]
    ) -> bool:
        line_dx, line_dy = self.x2 - self.x1, self.y2 - self.y1
        start_side = line_dx * (start[1] - self.y1) - line_dy * (start[0] - self.x1)
        end_side = line_dx * (end[1] - self.y1) - line_dy * (end[0] - self.x1)
        denominator = start_side - end_side
        if abs(denominator) < 1e-9:
            return False
        fraction = start_side / denominator
        intersection = (
            start[0] + fraction * (end[0] - start[0]),
            start[1] + fraction * (end[1] - start[1]),
        )
        projection = ((intersection[0] - self.x1) * line_dx + (intersection[1] - self.y1) * line_dy) / (self._length ** 2)
        return 0 <= fraction <= 1 and 0 <= projection <= 1


class RoiCounter:
    """Count a track immediately when its detected center is inside the ROI."""

    def __init__(self, roi: dict[str, int]) -> None:
        self.x, self.y, self.width, self.height = (
            int(roi[key]) for key in ("x", "y", "width", "height")
        )
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("ROI 参数无效")
        self.count = 0
        self.counted_ids: set[int] = set()

    def update(self, track_id: int, point: tuple[float, float]) -> bool:
        x, y = point
        if (track_id not in self.counted_ids
                and self.x <= x < self.x + self.width
                and self.y <= y < self.y + self.height):
            self.counted_ids.add(track_id)
            self.count += 1
            return True
        return False


def detection_center(box: Iterable[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(value) for value in box)
    return (x1 + x2) / 2, (y1 + y2) / 2
