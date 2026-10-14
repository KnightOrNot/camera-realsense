"""Command-line composition and dispatch; reusable switches live in arguments.py."""

from __future__ import annotations

import argparse
import json

from . import arguments, device, diagnostics
from .experiments import run_imu, run_video, video_mode
from .models import CaptureConfig, ExperimentConfig, OutputConfig, VideoConfig
from .storage import write_json


def add_capture_arguments(parser: argparse.ArgumentParser) -> None:
    for register in (arguments.add_duration_argument, arguments.add_timeout_argument,
                     arguments.add_max_timeouts_argument, arguments.add_min_fps_ratio_argument):
        register(parser)


def add_video_arguments(parser: argparse.ArgumentParser, command: str) -> None:
    width, height = ((424, 240) if command == "color" else
                     ((640, 480) if command in ("rgbd", "align", "snapshot", "record", "pointcloud") else (480, 270)))
    arguments.add_width_argument(parser, width)
    arguments.add_height_argument(parser, height)
    for register in (arguments.add_fps_argument, arguments.add_color_width_argument,
                     arguments.add_color_height_argument, arguments.add_color_fps_argument,
                     arguments.add_frames_argument, arguments.add_warmup_frames_argument,
                     arguments.add_pixel_argument, arguments.add_max_depth_argument,
                     arguments.add_preview_argument, arguments.add_output_dir_argument):
        register(parser)
    if command in ("snapshot", "record"):
        arguments.add_stream_argument(parser)
    if command in ("pointcloud", "record"):
        arguments.add_output_argument(parser, "输出 PLY 或 .db3 路径；默认使用 captures/时间戳路径")
    if command == "pointcloud":
        arguments.add_colored_argument(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RealSense USB2 功能测试；默认有限时采集并报告超时。")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    arguments.add_serial_argument(common)
    timed = argparse.ArgumentParser(add_help=False)
    add_capture_arguments(timed)
    info = sub.add_parser("info", parents=[common], help="设备信息和可用模式")
    arguments.add_profiles_argument(info)
    arguments.add_output_argument(info, "保存 JSON")
    calibration = sub.add_parser("calibration", parents=[common], help="读取内参、外参和深度单位")
    arguments.add_width_argument(calibration)
    arguments.add_height_argument(calibration)
    arguments.add_fps_argument(calibration)
    arguments.add_output_argument(calibration, "保存标定 JSON")
    options = sub.add_parser("options", parents=[common], help="列出传感器可读写的设置")
    arguments.add_sensor_argument(options)
    option = sub.add_parser("set-option", parents=[common], help="修改单个设置，默认 5 秒后恢复")
    for register in (arguments.add_sensor_argument, arguments.add_option_argument,
                     arguments.add_value_argument, arguments.add_restore_after_argument):
        register(option)
    imu = sub.add_parser("imu", parents=[common, timed], help="陀螺仪和加速度计测试并保存 CSV")
    arguments.add_accel_fps_argument(imu)
    arguments.add_gyro_fps_argument(imu)
    arguments.add_output_argument(imu, "CSV 路径，默认 captures/imu_时间.csv")
    descriptions = {
        "depth": "深度图和像素测距", "color": "RGB 彩色图", "infrared": "左侧红外灰度图",
        "rgbd": "同时采集彩色和深度", "align": "将深度对齐到彩色图",
        "snapshot": "保存一组图像和深度原始数据", "pointcloud": "生成几何/真实彩色点云并导出 PLY",
        "record": "录制原始流到 RealSense .db3 文件",
    }
    for command, description in descriptions.items():
        p = sub.add_parser(command, parents=[common, timed], help=description)
        add_video_arguments(p, command)
    return parser


def capture_config_from_args(args: argparse.Namespace) -> CaptureConfig:
    return CaptureConfig(duration=args.duration, timeout_ms=args.timeout_ms, max_timeouts=args.max_timeouts,
                         frames=getattr(args, "frames", 0), warmup_frames=getattr(args, "warmup_frames", 0),
                         min_fps_ratio=args.min_fps_ratio)


def video_config_from_args(args: argparse.Namespace) -> VideoConfig:
    pixel = getattr(args, "pixel", None)
    return VideoConfig(width=getattr(args, "width", 640), height=getattr(args, "height", 480),
                       fps=getattr(args, "fps", 5), color_width=getattr(args, "color_width", None),
                       color_height=getattr(args, "color_height", None), color_fps=getattr(args, "color_fps", None),
                       pixel=tuple(pixel) if pixel is not None else None, max_depth=getattr(args, "max_depth", 3))


def output_config_from_args(args: argparse.Namespace) -> OutputConfig:
    return OutputConfig(output=getattr(args, "output", None), output_dir=getattr(args, "output_dir", None),
                        preview=getattr(args, "preview", False))


def to_experiment_config(args: argparse.Namespace) -> ExperimentConfig:
    """Translate command arguments once; other modules never depend on Namespace."""
    return ExperimentConfig(command=args.command, serial=args.serial,
                            capture=capture_config_from_args(args), video=video_config_from_args(args),
                            output=output_config_from_args(args), stream=getattr(args, "stream", "depth"),
                            colored=getattr(args, "colored", False), accel_fps=getattr(args, "accel_fps", 200),
                            gyro_fps=getattr(args, "gyro_fps", 200))


def execute_command(args: argparse.Namespace) -> int:
    try:
        if args.command in ("info", "calibration"):
            result = (device.show_info(args.serial, args.profiles) if args.command == "info" else
                      device.read_calibration(args.serial, args.width, args.height, args.fps))
            diagnostics.log(json.dumps(result, ensure_ascii=False, indent=2))
            if args.output:
                write_json(args.output, result)
            return 0
        if args.command == "options":
            return device.camera_options(args.serial, args.sensor)
        if args.command == "set-option":
            return device.set_option(args.option, args.value, serial=args.serial,
                                     sensor_name=args.sensor, restore_after=args.restore_after)
        config = to_experiment_config(args)
        return run_imu(config) if args.command == "imu" else run_video(config)
    except KeyboardInterrupt as exc:
        return diagnostics.report_error(exc)
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        return diagnostics.report_error(exc)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("info", "calibration", "options", "set-option"):
        return execute_command(args)
    config = to_experiment_config(args)
    mode = "imu" if args.command == "imu" else video_mode(config)
    with diagnostics.status_session(mode):
        return execute_command(args)
