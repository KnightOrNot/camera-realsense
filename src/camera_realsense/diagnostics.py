"""Capture quality evaluation and console reporting."""

from __future__ import annotations

import shutil
import sys
import unicodedata
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import TextIO

from .models import CaptureStats, DepthMeasurement, ExperimentConfig, VideoQuality

_active_status: ContextVar[CaptureStatus | None] = ContextVar("capture_status", default=None)


def format_capture_status(mode: str, profiles: list[dict], fps: dict[str, float],
                          outcome: str = "", message: str = "") -> str:
    """Format actual active profiles and measured per-stream rates, without I/O."""
    parts = [f"mode={'rgb' if mode == 'color' else mode}"]
    for profile in profiles:
        name = profile["stream"]
        label = "rgb" if name == "color" else name
        rate = fps.get(name, 0.0)
        if "width" in profile:
            parts.append(f"{label}={profile['width']}x{profile['height']}@{rate:.1f}fps")
        else:
            parts.append(f"{label}={rate:.1f}Hz")
    if not profiles:
        parts.append("size=waiting fps=0.0")
    if outcome:
        parts.append(outcome)
    if message:
        parts.append(" ".join(message.split()))
    return " | ".join(parts)


def fit_terminal_line(message: str, columns: int) -> str:
    """Avoid wrapping, accounting for wide Chinese characters and combining marks."""
    limit = max(1, columns - 1)
    used = 0
    result = []
    for char in message:
        width = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
        if used + width > limit:
            return "".join(result)
        # Terminal control characters must not be introduced by SDK error text.
        if unicodedata.category(char).startswith("C"):
            continue
        result.append(char)
        used += width
    return "".join(result)


def format_depth_measurement(measurement: DepthMeasurement) -> str:
    x, y = measurement.pixel
    distance = f"{measurement.distance_m:.3f}m" if measurement.distance_m else "invalid"
    return f"pixel=({x},{y}):{distance} valid={measurement.valid_ratio:.1%}"


class CaptureStatus:
    """One terminal row, with a rolling one-second FPS window."""

    def __init__(self, mode: str, stream: TextIO | None = None):
        self.mode = mode
        self.stream = stream if stream is not None else sys.stdout
        self.interactive = self.stream.isatty()
        self.profiles: list[dict] = []
        self.fps: dict[str, float] = {}
        self.message = "正在启动相机"
        self.outcome = ""
        self.details = ""
        self.samples: deque[tuple[float, dict[str, int]]] = deque()
        self.last_refresh = float("-inf")
        self.closed = False

    def set_profiles(self, profiles: list[dict]) -> None:
        self.profiles = profiles

    def note(self, message: str) -> None:
        self.message = message

    def refresh(self, stats: CaptureStats, now: float, force: bool = False) -> None:
        if not force and now - self.last_refresh < 0.25:
            return
        self.samples.append((now, stats.counts.copy()))
        while len(self.samples) > 1 and self.samples[1][0] <= now - 1:
            self.samples.popleft()
        start, counts = self.samples[0]
        elapsed = now - start
        self.fps = {name: (count - counts.get(name, 0)) / elapsed if elapsed > 0 else 0.0
                    for name, count in stats.counts.items()}
        self.last_refresh = now
        self.draw()

    def text(self) -> str:
        message = "" if self.message == "采集中" else self.message
        if self.details:
            message = " | ".join(part for part in (message, self.details) if part)
        return format_capture_status(self.mode, self.profiles, self.fps, self.outcome, message)

    def draw(self) -> None:
        if self.interactive and not self.closed:
            line = fit_terminal_line(self.text(), shutil.get_terminal_size().columns)
            self.stream.write("\r\x1b[2K" + line)
            self.stream.flush()

    def finish(self) -> None:
        if self.closed:
            return
        if self.interactive:
            self.draw()
            self.stream.write("\n")
        else:
            # Redirected output gets a single clean final line, with no ANSI or CR.
            self.stream.write(self.text() + "\n")
        self.stream.flush()
        self.closed = True


def display_capture_status(status: CaptureStatus, stats: CaptureStats,
                           now: float, force: bool = False) -> None:
    """Reusable capture callback for single-line mode/resolution/FPS reporting."""
    status.refresh(stats, now, force)


@contextmanager
def status_session(mode: str, stream: TextIO | None = None):
    existing = _active_status.get()
    if existing is not None:
        yield existing
        return
    status = CaptureStatus(mode, stream)
    token = _active_status.set(status)
    try:
        status.draw()
        yield status
    except BaseException as exc:
        status.outcome = "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "ERROR"
        status.note(str(exc))
        raise
    finally:
        try:
            status.finish()
        finally:
            _active_status.reset(token)


def log(message: str) -> None:
    status = _active_status.get()
    if status is None:
        print(message, flush=True)
    else:
        status.note(message)


def report_result(status: CaptureStatus, summary: dict) -> None:
    status.outcome = "INTERRUPTED" if summary["reason"] == "interrupted" else summary["result"]
    if not status.message or status.message in ("正在启动相机", "采集中"):
        status.note(summary["reason"])


def report_error(error: BaseException) -> int:
    interrupted = isinstance(error, KeyboardInterrupt)
    status = _active_status.get()
    if status:
        status.outcome = "INTERRUPTED" if interrupted else "ERROR"
    log("已停止。" if interrupted else f"ERROR：{error}")
    return 130 if interrupted else 2


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
            "depth_measurement": asdict(quality.measurement) if quality.measurement else None,
            "average_fps": {k: round(v / max(stats.elapsed_s, 1e-9), 2) for k, v in stats.counts.items()}}


def summarize_imu(stats: CaptureStats, device: dict, config: ExperimentConfig) -> dict:
    slow = slow_streams(stats, {"accel": config.accel_fps, "gyro": config.gyro_fps}, config.capture.min_fps_ratio)
    passed = all(stats.counts.values()) and stats.timeouts == 0 and not slow
    return {"result": "PASS" if passed else "FAIL", "device": device, **vars(stats),
            "low_fps_streams": slow, "min_fps_ratio": config.capture.min_fps_ratio,
            "average_fps": {k: round(v / max(stats.elapsed_s, 1e-9), 2) for k, v in stats.counts.items()}}


def result_code(stats: CaptureStats, summary: dict) -> int:
    return 130 if stats.reason == "interrupted" else (0 if summary["result"] == "PASS" else 2)
