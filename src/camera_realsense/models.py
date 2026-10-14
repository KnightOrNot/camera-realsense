"""Configuration and result models shared by the camera modules."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .configuration import default_value, load_defaults

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
    duration: float = field(default_factory=lambda: default_value("capture", "duration"))
    timeout_ms: int = field(default_factory=lambda: default_value("capture", "timeout_ms"))
    max_timeouts: int = field(default_factory=lambda: default_value("capture", "max_timeouts"))
    frames: int = field(default_factory=lambda: default_value("capture", "frames"))
    warmup_frames: int = field(default_factory=lambda: default_value("capture", "warmup_frames"))
    min_fps_ratio: float = field(default_factory=lambda: default_value("capture", "min_fps_ratio"))


@dataclass(frozen=True)
class VideoConfig:
    width: int = field(default_factory=lambda: default_value("video", "width"))
    height: int = field(default_factory=lambda: default_value("video", "height"))
    fps: int = field(default_factory=lambda: default_value("video", "fps"))
    color_width: int | None = field(default_factory=lambda: default_value("video", "color_width"))
    color_height: int | None = field(default_factory=lambda: default_value("video", "color_height"))
    color_fps: int | None = field(default_factory=lambda: default_value("video", "color_fps"))
    pixel: tuple[int, int] | None = field(default_factory=lambda: default_value("video", "pixel"))
    max_depth: float = field(default_factory=lambda: default_value("video", "max_depth"))


@dataclass(frozen=True)
class OutputConfig:
    output: Path | None = field(default_factory=lambda: default_value("output", "output"))
    output_dir: Path | None = field(default_factory=lambda: default_value("output", "output_dir"))
    preview: bool = field(default_factory=lambda: default_value("output", "preview"))


@dataclass(frozen=True)
class ExperimentConfig:
    command: str
    serial: str | None = field(default_factory=lambda: default_value("common", "serial"))
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    stream: str = field(default_factory=lambda: default_value("video", "stream"))
    colored: bool = field(default_factory=lambda: default_value("video", "colored"))
    accel_fps: int = field(default_factory=lambda: default_value("imu", "accel_fps"))
    gyro_fps: int = field(default_factory=lambda: default_value("imu", "gyro_fps"))

    @classmethod
    def from_values(cls, command: str, values: dict[str, Any]) -> ExperimentConfig:
        return cls(command=command, serial=values["serial"],
                   capture=CaptureConfig(**{f.name: values[f.name] for f in fields(CaptureConfig)}),
                   video=VideoConfig(**{f.name: values[f.name] for f in fields(VideoConfig)}),
                   output=OutputConfig(**{f.name: values[f.name] for f in fields(OutputConfig)}),
                   stream=values["stream"], colored=values["colored"],
                   accel_fps=values["accel_fps"], gyro_fps=values["gyro_fps"])

    @classmethod
    def from_defaults(cls, command: str, config_path: Path | None = None) -> ExperimentConfig:
        """Apply the same command-specific TOML defaults as the CLI."""
        return cls.from_values(command, load_defaults(config_path).for_command(command))


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
