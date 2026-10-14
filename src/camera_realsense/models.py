"""Configuration and result models shared by the camera modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass
class CaptureStats:
    counts: dict[str, int] = field(default_factory=dict)
    complete_frames: int = 0
    timeouts: int = 0
    max_gap_s: float = 0.0
    elapsed_s: float = 0.0
    reason: str = "duration"


@dataclass(frozen=True)
class CaptureConfig:
    duration: float = 15
    timeout_ms: int = 5000
    max_timeouts: int = 2
    frames: int = 0
    warmup_frames: int = 0
    min_fps_ratio: float = 0.5


@dataclass(frozen=True)
class VideoConfig:
    width: int = 640
    height: int = 480
    fps: int = 5
    color_width: int | None = None
    color_height: int | None = None
    color_fps: int | None = None
    pixel: tuple[int, int] | None = None
    max_depth: float = 3


@dataclass(frozen=True)
class OutputConfig:
    output: Path | None = None
    output_dir: Path | None = None
    preview: bool = False


@dataclass(frozen=True)
class ExperimentConfig:
    command: str
    serial: str | None = None
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    stream: str = "depth"
    colored: bool = False
    accel_fps: int = 200
    gyro_fps: int = 200


@dataclass
class VideoQuality:
    saved: bool = False
    cloud_saved: bool = False
    saved_depth_valid: bool = True
    valid_depth_frames: int = 0
    aligned_valid_frames: int = 0
    units_m: float | None = None
    color_statistics: dict | None = None
    measurement: DepthMeasurement | None = None


@dataclass(frozen=True)
class DepthMeasurement:
    pixel: tuple[int, int]
    distance_m: float
    units_m: float
    valid_ratio: float


@dataclass(frozen=True)
class ImageSnapshot:
    images: dict[str, np.ndarray]
    metadata: dict
