"""Depth, color, alignment and pointcloud processing."""

from __future__ import annotations

import numpy as np
import pyrealsense2 as rs

from .device import profile_info
from .models import DepthMeasurement, ImageSnapshot


def depth_image(raw: np.ndarray, units: float, max_depth: float) -> np.ndarray:
    normalized = np.clip(raw.astype(np.float32) * units / max_depth, 0, 1)
    rgb = np.stack((1 - normalized, 1 - np.abs(2 * normalized - 1), normalized), axis=-1)
    result = (rgb * 255).astype(np.uint8)
    result[raw == 0] = 0
    return result


def cloud_arrays(depth, color, max_depth: float):
    pc = rs.pointcloud()
    if color:
        pc.map_to(color)
    points = pc.calculate(depth)
    vertices = np.asanyarray(points.get_vertices()).view(np.float32).reshape(-1, 3)
    keep = np.isfinite(vertices).all(axis=1) & (vertices[:, 2] > 0) & (vertices[:, 2] <= max_depth)
    if color:
        uv = np.asanyarray(points.get_texture_coordinates()).view(np.float32).reshape(-1, 2)
        keep &= np.isfinite(uv).all(axis=1) & (uv >= 0).all(axis=1) & (uv < 1).all(axis=1)
        image = np.asanyarray(color.get_data())
        pixels = (uv[keep] * [image.shape[1], image.shape[0]]).astype(np.int32)
        colors = image[pixels[:, 1], pixels[:, 0]].copy()
    else:
        colors = np.full((int(keep.sum()), 3), 200, dtype=np.uint8)
    return vertices[keep].copy(), colors


def measure_depth(depth, pixel: tuple[int, int] | None = None) -> DepthMeasurement:
    x, y = pixel or (depth.get_width() // 2, depth.get_height() // 2)
    if not (0 <= x < depth.get_width() and 0 <= y < depth.get_height()):
        raise ValueError("--pixel 超出了深度图范围。")
    raw = np.asanyarray(depth.get_data())
    return DepthMeasurement(pixel=(x, y), distance_m=depth.get_distance(x, y),
                            units_m=depth.get_units(), valid_ratio=float(np.count_nonzero(raw) / raw.size))


def color_statistics(frame) -> dict:
    rgb = np.asanyarray(frame.get_data())
    return {"min": int(rgb.min()), "max": int(rgb.max()),
            "mean": round(float(rgb.mean()), 3), "std": round(float(rgb.std()), 3)}


def prepare_snapshot(frames: dict, max_depth: float) -> ImageSnapshot:
    images, metadata = {}, {}
    for name, frame in frames.items():
        raw = np.asanyarray(frame.get_data())
        images[name] = raw.copy()
        metadata[name] = {"profile": profile_info(frame.profile),
                          "frame_number": frame.get_frame_number(),
                          "timestamp_ms": frame.get_timestamp()}
        if name == "depth":
            units = frame.get_units()
            metadata[name]["units_m"] = units
            images["depth_preview"] = depth_image(raw, units, max_depth)
    return ImageSnapshot(images=images, metadata=metadata)


def align_to_color(frames, aligner) -> dict:
    aligned = aligner.process(frames)
    depth, color = aligned.get_depth_frame(), aligned.get_color_frame()
    return {"depth": depth, "color": color} if depth and color else {}
