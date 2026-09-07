"""Immutable, CPU-only observations; not exercise judgments or user identities."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

COCO_KEYPOINT_NAMES = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

PoseStatus = Literal[
    "observable", "partial", "unobservable", "no_person", "multiple_people", "inference_error"
]


@dataclass(frozen=True, slots=True)
class Keypoint:
    # x / image_width, y / image_height; None means a non-finite/missing value.
    x: float | None
    y: float | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class PersonPose:
    # An index in ONE frame, never a persistent track_id or user_id.
    detection_index: int
    keypoints: tuple[Keypoint, ...]
    bbox_xyxy: tuple[float, float, float, float] | None
    confidence: float | None


@dataclass(frozen=True, slots=True)
class ProjectedAngles:
    left_knee: float | None = None
    right_knee: float | None = None
    left_hip: float | None = None
    right_hip: float | None = None

    def values(self) -> tuple[float | None, ...]:
        return self.left_knee, self.right_knee, self.left_hip, self.right_hip


@dataclass(frozen=True, slots=True)
class PoseSnapshot:
    session_id: str
    stream_epoch: int
    frame_id: int
    observed_at: float  # Process-local monotonic seconds at the adapter input.
    processed_at: float
    media_time_s: float | None  # Input PTS * time_base, not a wall/camera clock.
    width: int
    height: int
    model: str
    keypoint_threshold: float
    detections: tuple[PersonPose, ...]
    angles: ProjectedAngles
    status: PoseStatus
    processing_ms: float
    schema_version: str = field(default="coach.pose.v1", init=False)
    source: str = field(default="ultralytics_pose", init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_stale(self, now: float, max_age_s: float = 1.5) -> bool:
        return now - self.observed_at > max_age_s
