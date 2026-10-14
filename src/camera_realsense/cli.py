"""Command-line interface; argparse stays at this boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from . import device
from .diagnostics import log
from .experiments import run_imu, run_video
from .models import CaptureConfig, ExperimentConfig, OutputConfig, VideoConfig
from .storage import write_json


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的有限数值")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RealSense USB2 功能测试；默认有限时采集并报告超时。")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--serial", help="相机序列号；只有一台时自动选择")
    timed = argparse.ArgumentParser(add_help=False)
    timed.add_argument("--duration", type=positive_float, default=15, help="最长采集秒数，默认 15")
    timed.add_argument("--timeout-ms", type=positive_int, default=5000, help="每路流的无新数据超时，默认 5000 ms")
    timed.add_argument("--max-timeouts", type=positive_int, default=2, help="同一路连续超时多少次后停止，默认 2")
    timed.add_argument("--min-fps-ratio", type=float, default=0.5,
                       help="按时长测试时最低平均帧率/请求帧率，默认 0.5；0 关闭此项判断")
    info = sub.add_parser("info", parents=[common], help="设备信息和可用模式")
    info.add_argument("--profiles", action="store_true", help="列出当前 USB 连接可用的所有流参数")
    info.add_argument("--output", type=Path, help="保存 JSON")
    calibration = sub.add_parser("calibration", parents=[common], help="读取内参、外参和深度单位")
    for name, default in [("width", 640), ("height", 480), ("fps", 5)]:
        calibration.add_argument(f"--{name}", type=positive_int, default=default)
    calibration.add_argument("--output", type=Path, help="保存标定 JSON")
    options = sub.add_parser("options", parents=[common], help="列出传感器可读写的设置")
    options.add_argument("--sensor", choices=["depth", "color", "motion"], default="depth")
    option = sub.add_parser("set-option", parents=[common], help="修改单个设置，默认 5 秒后恢复")
    option.add_argument("--sensor", choices=["depth", "color", "motion"], default="depth")
    option.add_argument("--option", required=True, help="例如 emitter_enabled、enable_auto_exposure、exposure")
    option.add_argument("--value", type=float, required=True)
    option.add_argument("--restore-after", type=float, default=5, help="恢复前等待秒数，默认 5；0 表示保留")
    imu = sub.add_parser("imu", parents=[common, timed], help="陀螺仪和加速度计测试并保存 CSV")
    imu.add_argument("--accel-fps", type=positive_int, default=200)
    imu.add_argument("--gyro-fps", type=positive_int, default=200)
    imu.add_argument("--output", type=Path, help="CSV 路径，默认 captures/imu_时间.csv")
    descriptions = {
        "depth": "深度图和像素测距", "color": "RGB 彩色图", "infrared": "左侧红外灰度图",
        "rgbd": "同时采集彩色和深度", "align": "将深度对齐到彩色图",
        "snapshot": "保存一组图像和深度原始数据", "pointcloud": "生成几何/真实彩色点云并导出 PLY",
        "record": "录制原始流到 RealSense .db3 文件",
    }
    for command, description in descriptions.items():
        p = sub.add_parser(command, parents=[common, timed], help=description)
        width, height = ((424, 240) if command == "color" else
                         ((640, 480) if command in ("rgbd", "align", "snapshot", "record", "pointcloud") else (480, 270)))
        p.add_argument("--width", type=positive_int, default=width, help=f"主流宽度，默认 {width}")
        p.add_argument("--height", type=positive_int, default=height, help=f"主流高度，默认 {height}")
        p.add_argument("--fps", type=positive_int, default=5, help="主流帧率，默认 5")
        p.add_argument("--color-width", type=positive_int, help="彩色宽度，默认跟随 --width")
        p.add_argument("--color-height", type=positive_int, help="彩色高度，默认跟随 --height")
        p.add_argument("--color-fps", type=positive_int, help="彩色帧率，默认跟随 --fps")
        p.add_argument("--frames", type=int, default=0, help="完整新帧组目标；0 表示只按时长测试")
        p.add_argument("--warmup-frames", type=int, default=0,
                       help="先接收多少组完整帧再保存/处理/预览，默认 0；这些帧仍计入采集统计")
        p.add_argument("--pixel", type=int, nargs=2, metavar=("X", "Y"), help="测距像素，默认深度图中心")
        p.add_argument("--max-depth", type=positive_float, default=3, help="深度可视化/点云截断距离，默认 3 m")
        p.add_argument("--preview", action="store_true", help="显示输入图像窗口，需要 Tk 和桌面环境")
        p.add_argument("--output-dir", type=Path, help="保存第一组图像和统计 JSON")
        if command in ("snapshot", "record"):
            p.add_argument("--stream", choices=["depth", "color", "infrared", "rgbd"], default="depth")
        if command in ("pointcloud", "record"):
            p.add_argument("--output", type=Path, help="输出 PLY 或 .db3 路径；默认使用 captures/时间戳路径")
        if command == "pointcloud":
            p.add_argument("--colored", action="store_true", help="同时开彩色流，映射真实 RGB 颜色")
    return parser


def to_experiment_config(args: argparse.Namespace) -> ExperimentConfig:
    """Translate command arguments once; other modules never depend on Namespace."""
    pixel = getattr(args, "pixel", None)
    return ExperimentConfig(
        command=args.command,
        serial=args.serial,
        capture=CaptureConfig(
            duration=args.duration, timeout_ms=args.timeout_ms, max_timeouts=args.max_timeouts,
            frames=getattr(args, "frames", 0), warmup_frames=getattr(args, "warmup_frames", 0),
            min_fps_ratio=args.min_fps_ratio,
        ),
        video=VideoConfig(
            width=getattr(args, "width", 640), height=getattr(args, "height", 480),
            fps=getattr(args, "fps", 5), color_width=getattr(args, "color_width", None),
            color_height=getattr(args, "color_height", None), color_fps=getattr(args, "color_fps", None),
            pixel=tuple(pixel) if pixel is not None else None, max_depth=getattr(args, "max_depth", 3),
        ),
        output=OutputConfig(output=getattr(args, "output", None), output_dir=getattr(args, "output_dir", None),
                            preview=getattr(args, "preview", False)),
        stream=getattr(args, "stream", "depth"), colored=getattr(args, "colored", False),
        accel_fps=getattr(args, "accel_fps", 200), gyro_fps=getattr(args, "gyro_fps", 200),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "frames") and args.frames < 0:
        parser.error("--frames 不能为负数")
    if hasattr(args, "warmup_frames") and args.warmup_frames < 0:
        parser.error("--warmup-frames 不能为负数")
    if hasattr(args, "min_fps_ratio") and (not np.isfinite(args.min_fps_ratio) or
            not 0 <= args.min_fps_ratio <= 1):
        parser.error("--min-fps-ratio 必须在 0 到 1 之间")
    if args.command == "set-option" and (not np.isfinite(args.value) or
            not np.isfinite(args.restore_after) or args.restore_after < 0):
        parser.error("--value 必须是有限数值，--restore-after 必须是非负有限数值")
    try:
        if args.command in ("info", "calibration"):
            result = (device.show_info(args.serial, args.profiles) if args.command == "info" else
                      device.read_calibration(args.serial, args.width, args.height, args.fps))
            log(json.dumps(result, ensure_ascii=False, indent=2))
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
    except KeyboardInterrupt:
        log("已停止。")
        return 130
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        log(f"ERROR：{exc}")
        log("请先运行 info --profiles；检查 USB 连接、设备权限及是否有其他程序占用相机。")
        return 2
