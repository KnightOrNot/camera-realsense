"""Stream configuration, polling and pipeline lifetime management."""

from __future__ import annotations

import time
from contextlib import contextmanager

import pyrealsense2 as rs

from .diagnostics import log
from .models import CaptureConfig, CaptureStats, VideoConfig


def collect(pipe, config: CaptureConfig, consume, expected, preview=None, finished=None) -> CaptureStats:
    """Poll with per-stream watchdogs; even an empty stream has a finite deadline."""
    stats = CaptureStats(counts={name: 0 for name in expected})
    start = time.monotonic()
    last_seen: dict[str, float] = {name: start for name in expected}
    next_warning: dict[str, float] = {name: start + config.timeout_ms / 1000 for name in expected}
    streak: dict[str, int] = {name: 0 for name in expected}
    last_report = start
    try:
        while time.monotonic() - start < config.duration:
            if preview and not preview.pump():
                stats.reason = "window closed"
                break
            frames = pipe.poll_for_frames()
            now = time.monotonic()
            received = consume(frames) if frames else set()
            for name in received:
                stats.counts[name] += 1
                stats.max_gap_s = max(stats.max_gap_s, now - last_seen[name])
                last_seen[name] = now
                next_warning[name] = now + config.timeout_ms / 1000
                streak[name] = 0
            if set(expected).issubset(received):
                stats.complete_frames += 1
            stalled = [name for name in expected if now >= next_warning[name]]
            if stalled:
                stats.timeouts += 1
                for name in stalled:
                    streak[name] += 1
                    next_warning[name] = now + config.timeout_ms / 1000
                log(f"超时：{', '.join(stalled)} 连续 {config.timeout_ms} ms 未收到新数据 "
                    f"（累计 {stats.timeouts} 次）。")
            if any(count >= config.max_timeouts for count in streak.values()):
                stats.reason = "timeout limit"
                break
            if finished and finished():
                stats.reason = "artifact saved"
                break
            if config.frames and stats.complete_frames >= config.frames:
                stats.reason = "frame target"
                break
            if now - last_report >= 1:
                log(f"采集中 {now - start:.1f}s：{stats.counts}")
                last_report = now
            if not frames:
                time.sleep(0.005)
    except KeyboardInterrupt:
        stats.reason = "interrupted"
    finally:
        end = time.monotonic()
        stats.elapsed_s = end - start
        stats.max_gap_s = max(stats.max_gap_s, *(end - t for t in last_seen.values()))
    return stats


def configure_video(config: VideoConfig, device, mode):
    if mode not in ("depth", "color", "infrared", "rgbd"):
        raise ValueError(f"不支持的视频模式：{mode}")
    cfg = rs.config()
    cfg.enable_device(device.get_info(rs.camera_info.serial_number))
    requested = []
    if mode in ("depth", "rgbd"):
        requested.append((rs.stream.depth, 0, config.width, config.height, rs.format.z16, config.fps))
    if mode == "infrared":
        requested.append((rs.stream.infrared, 1, config.width, config.height, rs.format.y8, config.fps))
    if mode in ("color", "rgbd"):
        requested.append((rs.stream.color, 0, config.color_width or config.width,
                          config.color_height or config.height, rs.format.rgb8, config.color_fps or config.fps))
    profiles = [p for sensor in device.query_sensors() for p in sensor.get_stream_profiles()]
    for stream, index, width, height, fmt, fps in requested:
        supported = any(p.is_video_stream_profile() and p.stream_type() == stream
                        and p.stream_index() == index and p.format() == fmt and p.fps() == fps
                        and p.as_video_stream_profile().width() == width
                        and p.as_video_stream_profile().height() == height for p in profiles)
        if not supported:
            raise ValueError(f"当前连接未提供 {stream.name} {width}×{height}@{fps} {fmt.name}；"
                             "请运行 info --profiles 选择实际支持的参数。")
        cfg.enable_stream(stream, index, width, height, fmt, fps)
    return cfg, [item[0].name for item in requested]


@contextmanager
def pipeline_session(config: rs.config):
    """Always release a successfully started pipeline, including on callback errors."""
    pipe = rs.pipeline()
    started = False
    try:
        profile = pipe.start(config)
        started = True
        yield pipe, profile
    finally:
        if started:
            pipe.stop()


def configure_imu(serial: str, accel_fps: int, gyro_fps: int) -> rs.config:
    config = rs.config()
    config.enable_device(serial)
    config.enable_stream(rs.stream.accel, rs.format.motion_xyz32f, accel_fps)
    config.enable_stream(rs.stream.gyro, rs.format.motion_xyz32f, gyro_fps)
    return config


def enable_recording(config: rs.config, path) -> None:
    config.enable_record_to_file(str(path.resolve()))
