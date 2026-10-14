"""Capture quality evaluation and console reporting."""

from __future__ import annotations

from .models import CaptureStats, ExperimentConfig, VideoQuality


def log(message: str) -> None:
    print(message, flush=True)


def slow_streams(stats: CaptureStats, targets: dict, ratio: float) -> list[str]:
    """A few initial frames must not make a stalled timed experiment pass."""
    if stats.reason != "duration":
        return []
    return [name for name, fps in targets.items()
            if stats.counts[name] / max(stats.elapsed_s, 1e-9) < fps * ratio]


def summarize_video(stats: CaptureStats, device: dict, profiles: list[dict],
                    config: ExperimentConfig, quality: VideoQuality) -> dict:
    passed = all(stats.counts.values()) and stats.complete_frames > 0 and stats.timeouts == 0
    if config.capture.frames and stats.complete_frames < config.capture.frames and stats.reason != "artifact saved":
        passed = False
    if "depth" in stats.counts and quality.valid_depth_frames == 0:
        passed = False
    if config.command == "pointcloud" and not quality.cloud_saved:
        passed = False
    if config.command == "align" and not quality.aligned_valid_frames:
        passed = False
    if config.command == "snapshot" and (not quality.saved or not quality.saved_depth_valid):
        passed = False
    targets = {p["stream"]: p["fps"] for p in profiles}
    slow = slow_streams(stats, targets, config.capture.min_fps_ratio)
    if slow:
        passed = False
        log(f"帧率不足：{', '.join(slow)} 实测平均帧率低于请求帧率的 {config.capture.min_fps_ratio:.0%}。")
    return {"result": "PASS" if passed else "FAIL", "device": device, "profiles": profiles,
            **vars(stats), "depth_units_m": quality.units_m,
            "valid_depth_frames": quality.valid_depth_frames, "aligned_valid_frames": quality.aligned_valid_frames,
            "low_fps_streams": slow, "min_fps_ratio": config.capture.min_fps_ratio,
            "color_statistics": quality.color_statistics,
            "average_fps": {k: round(v / max(stats.elapsed_s, 1e-9), 2) for k, v in stats.counts.items()}}


def summarize_imu(stats: CaptureStats, device: dict, config: ExperimentConfig) -> dict:
    slow = slow_streams(stats, {"accel": config.accel_fps, "gyro": config.gyro_fps}, config.capture.min_fps_ratio)
    passed = all(stats.counts.values()) and stats.timeouts == 0 and not slow
    return {"result": "PASS" if passed else "FAIL", "device": device, **vars(stats),
            "low_fps_streams": slow, "min_fps_ratio": config.capture.min_fps_ratio,
            "average_fps": {k: round(v / max(stats.elapsed_s, 1e-9), 2) for k, v in stats.counts.items()}}


def result_code(stats: CaptureStats, summary: dict) -> int:
    return 130 if stats.reason == "interrupted" else (0 if summary["result"] == "PASS" else 2)
