"""RealSense discovery, calibration and sensor controls."""

from __future__ import annotations

import json
import time

import pyrealsense2 as rs

from .diagnostics import log


def device_info(device) -> dict:
    result = {}
    for name in ("name", "serial_number", "firmware_version", "usb_type_descriptor"):
        key = getattr(rs.camera_info, name)
        if device.supports(key):
            result[name] = device.get_info(key)
    return result


def select_device(serial: str | None):
    devices = list(rs.context().query_devices())
    if serial:
        devices = [d for d in devices if d.get_info(rs.camera_info.serial_number) == serial]
    if not devices:
        raise RuntimeError("未找到相机，请检查连接、--serial 和 udev 权限规则。")
    if len(devices) != 1:
        raise ValueError("检测到多台相机，请用 --serial 明确指定。")
    device = devices[0]
    log(json.dumps(device_info(device), ensure_ascii=False))
    return device


def profile_info(profile) -> dict:
    result = {"stream": profile.stream_type().name, "index": profile.stream_index(),
              "format": profile.format().name, "fps": profile.fps()}
    if profile.is_video_stream_profile():
        video = profile.as_video_stream_profile()
        result.update(width=video.width(), height=video.height())
    return result


def show_info(serial: str | None = None, profiles: bool = False) -> dict:
    device = select_device(serial)
    result = device_info(device)
    result["sensors"] = []
    for sensor in device.query_sensors():
        entry: dict[str, object] = {"name": sensor.get_info(rs.camera_info.name)}
        if profiles:
            entry["profiles"] = [profile_info(p) for p in sensor.get_stream_profiles()]
        result["sensors"].append(entry)
    return result


def read_calibration(serial: str | None = None, width: int = 640, height: int = 480, fps: int = 5) -> dict:
    device = select_device(serial)
    profiles = {}
    for sensor in device.query_sensors():
        for profile in sensor.get_stream_profiles():
            if not profile.is_video_stream_profile():
                continue
            video = profile.as_video_stream_profile()
            if (video.width(), video.height(), video.fps()) != (width, height, fps):
                continue
            if video.stream_type() in (rs.stream.depth, rs.stream.color):
                profiles.setdefault(video.stream_type(), video)
    if not all(stream in profiles for stream in (rs.stream.depth, rs.stream.color)):
        raise ValueError("该模式没有同时对应的深度和彩色标定，请先运行 info --profiles。")
    result = {"device": device_info(device),
              "depth_units_m": device.first_depth_sensor().get_depth_scale()}
    for stream, profile in profiles.items():
        intr = profile.get_intrinsics()
        result[stream.name] = {
            "width": intr.width, "height": intr.height, "fx": intr.fx, "fy": intr.fy,
            "ppx": intr.ppx, "ppy": intr.ppy, "model": intr.model.name,
            "coeffs": list(intr.coeffs),
        }
    extr = profiles[rs.stream.depth].get_extrinsics_to(profiles[rs.stream.color])
    result["depth_to_color"] = {"rotation": list(extr.rotation),
                                "translation_m": list(extr.translation)}
    return result


def get_sensor(device, name: str):
    for sensor in device.query_sensors():
        if name == "depth" and sensor.is_depth_sensor():
            return sensor
        streams = {p.stream_type() for p in sensor.get_stream_profiles()}
        if name == "color" and rs.stream.color in streams:
            return sensor
        if name == "motion" and rs.stream.gyro in streams:
            return sensor
    raise ValueError(f"相机没有 {name} 传感器。")


def camera_options(serial: str | None = None, sensor_name: str = "depth") -> int:
    sensor = get_sensor(select_device(serial), sensor_name)
    for option in sensor.get_supported_options():
        try:
            limits = sensor.get_option_range(option)
            log(f"{option.name}: value={sensor.get_option(option):g}, "
                f"range=[{limits.min:g}, {limits.max:g}], step={limits.step:g}, "
                f"default={limits.default:g}, readonly={sensor.is_option_read_only(option)}")
        except RuntimeError as exc:
            # Some advertised telemetry options only work while streaming.
            log(f"{option.name}: 当前不可读取（{exc}）")
    return 0


def set_option(option_name: str, value: float, *, serial: str | None = None,
               sensor_name: str = "depth", restore_after: float = 5) -> int:
    sensor = get_sensor(select_device(serial), sensor_name)
    option = getattr(rs.option, option_name, None)
    if option is None or not sensor.supports(option):
        raise ValueError("该选项不受支持，请先用 options 查看可用选项名。")
    if sensor.is_option_read_only(option):
        raise ValueError("该选项只读。")
    limits = sensor.get_option_range(option)
    if not limits.min <= value <= limits.max:
        raise ValueError(f"取值超出范围 [{limits.min}, {limits.max}]。")
    previous = sensor.get_option(option)
    changed = False
    try:
        sensor.set_option(option, value)
        changed = True
        log(f"{option_name}: {previous:g} → {sensor.get_option(option):g}")
        if restore_after > 0:
            log(f"{restore_after:g} 秒后恢复原值；Ctrl+C 也会恢复。")
            end = time.monotonic() + restore_after
            while time.monotonic() < end:
                time.sleep(max(0, min(0.1, end - time.monotonic())))
        else:
            log("保留新值。它可能影响后续采集，请记录原值。")
    finally:
        if changed and restore_after > 0:
            sensor.set_option(option, previous)
            log(f"已恢复 {option_name}={previous:g}")
    return 0
