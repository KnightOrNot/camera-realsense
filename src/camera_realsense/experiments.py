"""Coordinate camera experiments using configuration objects, independent of argparse."""

from __future__ import annotations

from dataclasses import replace
from functools import partial

import numpy as np
import pyrealsense2 as rs

from . import capture, device, diagnostics, processing, storage
from .models import ExperimentConfig, VideoQuality
from .preview import preview_session, show_preview


def video_mode(config: ExperimentConfig) -> str:
    if config.command in ("snapshot", "record"):
        return config.stream
    if config.command in ("rgbd", "align") or (config.command == "pointcloud" and config.colored):
        return "rgbd"
    return "depth" if config.command == "pointcloud" else config.command


def run_video(config: ExperimentConfig) -> int:
    with diagnostics.status_session(video_mode(config)) as status:
        return _run_video(config, status)


def update_video_quality(selected: dict, new: set[str], config: ExperimentConfig,
                         quality: VideoQuality) -> None:
    """Depth measurement (--pixel) and color diagnostics are reusable frame features."""
    if "color" in new:
        quality.color_statistics = processing.color_statistics(selected["color"])
    if "depth" in selected:
        depth = selected["depth"].as_depth_frame()
        selected["depth"] = depth
        quality.units_m = depth.get_units()
        if "depth" in new:
            quality.measurement = processing.measure_depth(depth, config.video.pixel)
            quality.valid_depth_frames += int(quality.measurement.valid_ratio > 0)


def save_snapshot(folder, selected: dict, quality: VideoQuality, max_depth: float) -> None:
    """Apply --output-dir once, preserving raw depth and metadata."""
    if folder is None or quality.saved:
        return
    storage.save_images(folder, processing.prepare_snapshot(selected, max_depth))
    if "depth" in selected:
        quality.saved_depth_valid = bool(np.count_nonzero(np.asanyarray(selected["depth"].get_data())))
    quality.saved = True


def export_pointcloud(depth, color, path, quality: VideoQuality, max_depth: float) -> None:
    """Apply --colored / --max-depth and export the first nonempty cloud."""
    if depth is None or quality.cloud_saved:
        return
    vertices, colors = processing.cloud_arrays(depth, color, max_depth)
    if len(vertices):
        storage.write_ply(path, vertices, colors)
        quality.cloud_saved = True


def _run_video(config: ExperimentConfig, status: diagnostics.CaptureStatus) -> int:
    camera = device.select_device(config.serial)
    cfg, expected = capture.configure_video(config.video, camera, video_mode(config))
    folder = config.output.output_dir
    if config.command == "snapshot" and folder is None:
        folder = storage.output_path("snapshot")
    recording = None
    if config.command == "record":
        recording = storage.prepare_recording(config.output.output or storage.output_path("record", ".db3"))
        capture.enable_recording(cfg, recording)
    cloud_path = config.output.output or storage.output_path("cloud", ".ply")
    quality = VideoQuality()
    complete_observed = 0
    last_numbers = {}
    preview = None
    aligner = rs.align(rs.stream.color) if config.command == "align" else None

    def consume(frames):
        nonlocal complete_observed
        selected = {}
        for name in expected:
            frame = frames.first_or_default(getattr(rs.stream, name))
            if frame:
                selected[name] = frame.as_video_frame()
        new = {name for name, frame in selected.items()
               if last_numbers.get(name) != frame.get_frame_number()}
        for name in new:
            last_numbers[name] = selected[name].get_frame_number()
        update_video_quality(selected, new, config, quality)
        if quality.measurement:
            status.details = diagnostics.format_depth_measurement(quality.measurement)
        depth = selected.get("depth")
        if not set(expected).issubset(selected) or not new:
            return new
        if set(expected).issubset(new):
            complete_observed += 1
        if not capture.warmup_complete(config.capture, complete_observed):
            return new
        if aligner:
            selected = processing.align_to_color(frames, aligner)
            if not selected:
                return new
            quality.aligned_valid_frames += int(np.count_nonzero(np.asanyarray(selected["depth"].get_data())) > 0)
        save_snapshot(folder, selected, quality, config.video.max_depth)
        if config.command == "pointcloud":
            export_pointcloud(depth, selected.get("color"), cloud_path, quality, config.video.max_depth)
        show_preview(preview, selected, config.video.max_depth)
        return new

    def finished():
        return not config.output.preview and ((config.command == "snapshot" and quality.saved)
                or (config.command == "pointcloud" and quality.cloud_saved))

    with capture.pipeline_session(cfg) as (pipe, profile):
        active_profiles = [device.profile_info(p) for p in profile.get_streams()]
        status.set_profiles(active_profiles)
        status.note("采集中")
        with preview_session(config.output.preview) as preview:
            stats = capture.collect(pipe, config.capture, consume, expected, preview, finished,
                                    report=partial(diagnostics.display_capture_status, status))
    summary = diagnostics.summarize_video(stats, device.device_info(camera), active_profiles, config, quality)
    if "depth" in expected and not quality.valid_depth_frames:
        diagnostics.log("深度图全为 0：收到帧不等于测距有效，请检查场景、距离和采集状态。")
    if quality.color_statistics and quality.color_statistics["max"] <= 1:
        diagnostics.log("彩色图接近全黑。收到彩色帧不等于图像质量正常；请检查光照、镜头遮挡和曝光，或增加预热帧数。")
    if folder:
        storage.write_json(folder / "summary.json", summary)
    if recording:
        storage.write_json(recording.with_suffix(".json"), summary)
        diagnostics.log(f"录像：{recording}。请结合统计判断，文件存在不代表录到了有效数据。")
    if config.command == "pointcloud":
        storage.write_json(cloud_path.with_suffix(".json"), summary)
    diagnostics.report_result(status, summary)
    return diagnostics.result_code(stats, summary)


def run_imu(config: ExperimentConfig) -> int:
    with diagnostics.status_session("imu") as status:
        return _run_imu(config, status)


def _run_imu(config: ExperimentConfig, status: diagnostics.CaptureStatus) -> int:
    camera = device.select_device(config.serial)
    cfg = capture.configure_imu(camera.get_info(rs.camera_info.serial_number), config.accel_fps, config.gyro_fps)
    path = config.output.output or storage.output_path("imu", ".csv")
    seen = {}
    columns = ["stream", "frame_number", "timestamp_ms", "timestamp_domain", "x", "y", "z", "unit"]
    with storage.csv_output(path, columns) as writer:
        def consume(frames):
            received = set()
            for frame in frames:
                name = frame.profile.stream_type().name
                if name not in ("gyro", "accel") or seen.get(name) == frame.get_frame_number():
                    continue
                seen[name] = frame.get_frame_number()
                received.add(name)
                data = frame.as_motion_frame().get_motion_data()
                unit = "m/s^2" if name == "accel" else "rad/s"
                writer.writerow([name, frame.get_frame_number(), frame.get_timestamp(),
                                 frame.get_frame_timestamp_domain().name, data.x, data.y, data.z, unit])
            return received

        with capture.pipeline_session(cfg) as (pipe, profile):
            status.set_profiles([device.profile_info(p) for p in profile.get_streams()])
            status.note("采集中")
            stats = capture.collect(pipe, replace(config.capture, frames=0), consume, ["accel", "gyro"],
                                    report=partial(diagnostics.display_capture_status, status))
    summary = diagnostics.summarize_imu(stats, device.device_info(camera), config)
    storage.write_json(path.with_suffix(".json"), summary)
    diagnostics.log(f"IMU CSV：{path}")
    diagnostics.report_result(status, summary)
    return diagnostics.result_code(stats, summary)
