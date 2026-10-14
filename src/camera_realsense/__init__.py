"""RealSense experiments: public configuration and result models.

CLI entry point: camera_realsense.cli.main.
Experiment entry points: camera_realsense.experiments.run_video / run_imu.
Importing the package does not initialize the SDK or open a camera.
"""

from .models import (
    CaptureConfig,
    CaptureStats,
    DepthMeasurement,
    ExperimentConfig,
    ImageSnapshot,
    OutputConfig,
    VideoConfig,
)

__all__ = [
    "CaptureConfig",
    "CaptureStats",
    "DepthMeasurement",
    "ExperimentConfig",
    "ImageSnapshot",
    "OutputConfig",
    "VideoConfig",
]
