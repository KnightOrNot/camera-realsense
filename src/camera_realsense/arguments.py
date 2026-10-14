"""Reusable argument registration functions; behavior stays in the feature modules."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("不能为负数")
    return number


def finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError("必须是有限数值")
    return number


def positive_float(value: str) -> float:
    number = finite_float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的有限数值")
    return number


def nonnegative_float(value: str) -> float:
    number = finite_float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("必须是非负有限数值")
    return number


def fps_ratio(value: str) -> float:
    number = finite_float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("必须在 0 到 1 之间")
    return number


def add_serial_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--serial", help="相机序列号；只有一台时自动选择")


def add_duration_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--duration", type=positive_float, default=15, help="最长采集秒数，默认 15")


def add_timeout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout-ms", type=positive_int, default=5000, help="每路流的无新数据超时，默认 5000 ms")


def add_max_timeouts_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-timeouts", type=positive_int, default=2, help="同一路连续超时多少次后停止，默认 2")


def add_min_fps_ratio_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-fps-ratio", type=fps_ratio, default=0.5,
                        help="按时长测试时最低平均帧率/请求帧率，默认 0.5；0 关闭此项判断")


def add_profiles_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profiles", action="store_true", help="列出当前 USB 连接可用的所有流参数")


def add_output_argument(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument("--output", type=Path, help=help_text)


def add_width_argument(parser: argparse.ArgumentParser, default: int = 640) -> None:
    parser.add_argument("--width", type=positive_int, default=default, help=f"主流宽度，默认 {default}")


def add_height_argument(parser: argparse.ArgumentParser, default: int = 480) -> None:
    parser.add_argument("--height", type=positive_int, default=default, help=f"主流高度，默认 {default}")


def add_fps_argument(parser: argparse.ArgumentParser, default: int = 5) -> None:
    parser.add_argument("--fps", type=positive_int, default=default, help=f"主流帧率，默认 {default}")


def add_sensor_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sensor", choices=["depth", "color", "motion"], default="depth")


def add_option_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--option", required=True, help="例如 emitter_enabled、enable_auto_exposure、exposure")


def add_value_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--value", type=finite_float, required=True)


def add_restore_after_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--restore-after", type=nonnegative_float, default=5,
                        help="恢复前等待秒数，默认 5；0 表示保留")


def add_accel_fps_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--accel-fps", type=positive_int, default=200)


def add_gyro_fps_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gyro-fps", type=positive_int, default=200)


def add_color_width_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--color-width", type=positive_int, help="彩色宽度，默认跟随 --width")


def add_color_height_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--color-height", type=positive_int, help="彩色高度，默认跟随 --height")


def add_color_fps_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--color-fps", type=positive_int, help="彩色帧率，默认跟随 --fps")


def add_frames_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--frames", type=nonnegative_int, default=0,
                        help="完整新帧组目标；0 表示只按时长测试")


def add_warmup_frames_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--warmup-frames", type=nonnegative_int, default=0,
                        help="先接收多少组完整帧再保存/处理/预览，默认 0；这些帧仍计入采集统计")


def add_pixel_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pixel", type=int, nargs=2, metavar=("X", "Y"), help="测距像素，默认深度图中心")


def add_max_depth_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-depth", type=positive_float, default=3,
                        help="深度可视化/点云截断距离，默认 3 m")


def add_preview_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preview", action="store_true", help="显示输入图像窗口，需要 Tk 和桌面环境")


def add_output_dir_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, help="保存第一组图像和统计 JSON")


def add_stream_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stream", choices=["depth", "color", "infrared", "rgbd"], default="depth")


def add_colored_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--colored", action="store_true", help="同时开彩色流，映射真实 RGB 颜色")
