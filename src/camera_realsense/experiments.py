"""Coordinate camera experiments using configuration objects, independent of argparse."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import numpy as np
import pyrealsense2 as rs

from . import capture, device, diagnostics, processing, storage
from .models import ExperimentConfig, VideoQuality
from .preview import Preview


def video_mode(config: ExperimentConfig) -> str:
    if config.command in ("snapshot", "record"):
        return config.stream
    if config.command in ("rgbd", "align") or (config.command == "pointcloud" and config.colored):
        return "rgbd"
    return "depth" if config.command == "pointcloud" else config.command


def run_video(config: ExperimentConfig) -> int:
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
    last_print = 0.0
    preview = None
    aligner = rs.align(rs.stream.color) if config.command == "align" else None

    def consume(frames):
        nonlocal complete_observed, last_print
        selected = {}
        for name in expected:
            frame = frames.first_or_default(getattr(rs.stream, name))
            if frame:
                selected[name] = frame.as_video_frame()
        new = {name for name, frame in selected.items()
               if last_numbers.get(name) != frame.get_frame_number()}
        for name in new:
            last_numbers[name] = selected[name].get_frame_number()
        if "color" in new:
            quality.color_statistics = processing.color_statistics(selected["color"])
        depth = selected.get("depth")
        if depth is not None:
            depth = depth.as_depth_frame()
            selected["depth"] = depth
            raw = np.asanyarray(depth.get_data())
            quality.units_m = depth.get_units()
            if "depth" in new:
                quality.valid_depth_frames += int(np.count_nonzero(raw) > 0)
                if time.monotonic() - last_print >= 1:
                    measurement = processing.measure_depth(depth, config.video.pixel)
                    x, y = measurement.pixel
                    distance = f"{measurement.distance_m:.3f} m" if measurement.distance_m else "无有效深度"
                    diagnostics.log(f"depth #{depth.get_frame_number()}：像素({x},{y}) {distance}；"
                                    f"整帧有效像素 {measurement.valid_ratio:.1%}")
                    last_print = time.monotonic()
        if not set(expected).issubset(selected) or not new:
            return new
        if set(expected).issubset(new):
            complete_observed += 1
        if complete_observed <= config.capture.warmup_frames:
            return new
        if aligner:
            selected = processing.align_to_color(frames, aligner)
            if not selected:
                return new
            quality.aligned_valid_frames += int(np.count_nonzero(np.asanyarray(selected["depth"].get_data())) > 0)
        if folder and not quality.saved:
            storage.save_images(folder, processing.prepare_snapshot(selected, config.video.max_depth))
            if "depth" in selected:
                quality.saved_depth_valid = bool(np.count_nonzero(np.asanyarray(selected["depth"].get_data())))
            quality.saved = True
        if config.command == "pointcloud" and not quality.cloud_saved and depth is not None:
            vertices, colors = processing.cloud_arrays(depth, selected.get("color"), config.video.max_depth)
            if len(vertices):
                storage.write_ply(cloud_path, vertices, colors)
                quality.cloud_saved = True
        if preview:
            images = []
            for name, frame in selected.items():
                raw = np.asanyarray(frame.get_data())
                images.append(processing.depth_image(raw, frame.get_units(), config.video.max_depth)
                              if name == "depth" else raw)
            preview.show(images)
        return new

    def finished():
        return ((config.command == "snapshot" and quality.saved)
                or (config.command == "pointcloud" and quality.cloud_saved))

    try:
        with capture.pipeline_session(cfg) as (pipe, profile):
            active_profiles = [device.profile_info(p) for p in profile.get_streams()]
            diagnostics.log("已启动：" + json.dumps(active_profiles, ensure_ascii=False))
            if config.output.preview:
                preview = Preview()
            stats = capture.collect(pipe, config.capture, consume, expected, preview, finished)
    finally:
        if preview:
            preview.destroy()
    summary = diagnostics.summarize_video(stats, device.device_info(camera), active_profiles, config, quality)
    diagnostics.log(json.dumps(summary, ensure_ascii=False, indent=2))
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
    return diagnostics.result_code(stats, summary)


def run_imu(config: ExperimentConfig) -> int:
    camera = device.select_device(config.serial)
    cfg = capture.configure_imu(camera.get_info(rs.camera_info.serial_number), config.accel_fps, config.gyro_fps)
    path = config.output.output or storage.output_path("imu", ".csv")
    seen = {}
    last_print = 0.0
    columns = ["stream", "frame_number", "timestamp_ms", "timestamp_domain", "x", "y", "z", "unit"]
    with storage.csv_output(path, columns) as writer:
        def consume(frames):
            nonlocal last_print
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
                if time.monotonic() - last_print >= 1:
                    diagnostics.log(f"{name}: ({data.x:.4f}, {data.y:.4f}, {data.z:.4f}) {unit}")
                    last_print = time.monotonic()
            return received

        with capture.pipeline_session(cfg) as (pipe, profile):
            diagnostics.log("已启动：" + json.dumps([device.profile_info(p) for p in profile.get_streams()]))
            stats = capture.collect(pipe, replace(config.capture, frames=0), consume, ["accel", "gyro"])
    summary = diagnostics.summarize_imu(stats, device.device_info(camera), config)
    storage.write_json(path.with_suffix(".json"), summary)
    diagnostics.log(json.dumps(summary, ensure_ascii=False, indent=2))
    diagnostics.log(f"IMU CSV：{path}")
    return diagnostics.result_code(stats, summary)
