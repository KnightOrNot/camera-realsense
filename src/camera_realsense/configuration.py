"""Load and validate the single source of argument defaults, without camera access."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import arguments

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.toml"
GROUP_FIELDS = {
    "common": {"serial"},
    "capture": {"duration", "timeout_ms", "max_timeouts", "frames", "warmup_frames", "min_fps_ratio"},
    "video": {"width", "height", "fps", "color_width", "color_height", "color_fps", "pixel", "max_depth", "stream", "colored"},
    "output": {"preview", "output", "output_dir"},
    "imu": {"accel_fps", "gyro_fps"},
}
VIDEO_COMMANDS = {"depth", "color", "infrared", "rgbd", "align", "snapshot", "pointcloud", "record"}
VIDEO_FIELDS = GROUP_FIELDS["common"] | GROUP_FIELDS["capture"] | GROUP_FIELDS["video"] | GROUP_FIELDS["output"]
COMMAND_FIELDS = {
    name: VIDEO_FIELDS - {"stream", "colored", "output"} for name in VIDEO_COMMANDS
}
COMMAND_FIELDS.update({
    "snapshot": VIDEO_FIELDS - {"colored", "output"},
    "pointcloud": VIDEO_FIELDS - {"stream"},
    "record": VIDEO_FIELDS - {"colored"},
    "info": {"serial", "profiles", "output"},
    "calibration": {"serial", "width", "height", "fps", "output"},
    "options": {"serial", "sensor"},
    "set-option": {"serial", "sensor", "option", "value", "restore_after"},
    "imu": {"serial", "duration", "timeout_ms", "max_timeouts", "min_fps_ratio", "accel_fps", "gyro_fps", "output"},
})


def convert_default(name: str, value: Any) -> Any:
    """TOML values use strict native types and the same ranges as CLI arguments."""
    if name in {"preview", "profiles", "colored"}:
        if type(value) is not bool:
            raise ValueError("必须是 true 或 false")
        return value
    if name == "pixel":
        if not isinstance(value, list) or (value and len(value) != 2):
            raise ValueError("必须是 [] 或 [X, Y]")
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("像素坐标必须是非负整数")
        return tuple(value) if value else None
    if name in {"serial", "output", "output_dir", "option", "sensor", "stream"}:
        if not isinstance(value, str):
            raise ValueError("必须是字符串")
        if name == "sensor" and value not in {"depth", "color", "motion"}:
            raise ValueError("必须是 depth、color 或 motion")
        if name == "stream" and value not in {"depth", "color", "infrared", "rgbd"}:
            raise ValueError("必须是 depth、color、infrared 或 rgbd")
        if name in {"output", "output_dir"}:
            return Path(value) if value else None
        return value or None
    if name == "value" and value == "":
        return None
    integer_fields = {"width", "height", "fps", "color_width", "color_height", "color_fps",
                      "timeout_ms", "max_timeouts", "frames", "warmup_frames", "accel_fps", "gyro_fps"}
    if name in integer_fields:
        if type(value) is not int:
            raise ValueError("必须是整数")
        if name.startswith("color_") and value == 0:
            return None
        validator = arguments.nonnegative_int if name in {"frames", "warmup_frames"} else arguments.positive_int
    else:
        if type(value) not in (int, float):
            raise ValueError("必须是数值")
        validator = {"duration": arguments.nonnegative_float, "max_depth": arguments.positive_float,
                     "min_fps_ratio": arguments.fps_ratio, "restore_after": arguments.nonnegative_float,
                     "value": arguments.finite_float}[name]
    return validator(str(value))


@dataclass(frozen=True)
class Defaults:
    path: Path
    groups: dict[str, dict[str, Any]]
    commands: dict[str, dict[str, Any]]

    def for_command(self, command: str) -> dict[str, Any]:
        if command not in COMMAND_FIELDS:
            raise ValueError(f"未知命令：{command}")
        values = {}
        for group in GROUP_FIELDS:
            values.update(self.groups[group])
        values.update(self.commands.get(command, {}))
        return values


def load_defaults(path: Path | None = None) -> Defaults:
    source = (path or DEFAULT_CONFIG_PATH).expanduser().resolve()
    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
        unknown = set(raw) - (set(GROUP_FIELDS) | {"commands"})
        if unknown:
            raise ValueError(f"未知分组：{', '.join(sorted(unknown))}")
        groups = {}
        for group, keys in GROUP_FIELDS.items():
            table = raw.get(group)
            if not isinstance(table, dict):
                raise ValueError(f"缺少 [{group}] 分组")
            missing, extra = keys - set(table), set(table) - keys
            if missing:
                raise ValueError(f"[{group}] 缺少默认值：{', '.join(sorted(missing))}")
            if extra:
                raise ValueError(f"[{group}] 未知参数：{', '.join(sorted(extra))}")
            groups[group] = _convert_table(group, table)
        command_tables = raw.get("commands", {})
        if not isinstance(command_tables, dict):
            raise ValueError("[commands] 必须是表")
        commands = {}
        for command, table in command_tables.items():
            if command not in COMMAND_FIELDS:
                raise ValueError(f"未知命令分组：[commands.{command}]")
            if not isinstance(table, dict):
                raise ValueError(f"[commands.{command}] 必须是表")
            extra = set(table) - COMMAND_FIELDS[command]
            if extra:
                raise ValueError(f"[commands.{command}] 不支持参数：{', '.join(sorted(extra))}")
            commands[command] = _convert_table(f"commands.{command}", table)
        # Command-only defaults must be present in their own table.
        for command, keys in {"info": {"profiles"}, "options": {"sensor"},
                              "set-option": {"sensor", "option", "value", "restore_after"}}.items():
            missing = keys - commands.get(command, {}).keys()
            if missing:
                raise ValueError(f"[commands.{command}] 缺少默认值：{', '.join(sorted(missing))}")
        return Defaults(source, groups, commands)
    except (OSError, ValueError, argparse.ArgumentTypeError) as exc:
        raise ValueError(f"配置文件 {source}：{exc}") from exc


def _convert_table(section: str, table: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for key, value in table.items():
        try:
            values[key] = convert_default(key, value)
        except (ValueError, argparse.ArgumentTypeError) as exc:
            raise ValueError(f"{section}.{key}：{exc}") from exc
    return values


def default_value(group: str, name: str) -> Any:
    """Lazy model defaults keep importing camera_realsense free of filesystem I/O."""
    return load_defaults().groups[group][name]


def command_default(command: str, name: str) -> Any:
    return load_defaults().for_command(command)[name]


def apply_defaults(parser: argparse.ArgumentParser, command: str, defaults: Defaults) -> None:
    values = defaults.for_command(command)
    selected = {}
    for action in parser._actions:
        if action.dest in values:
            selected[action.dest] = values[action.dest]
            if action.required and values[action.dest] is not None:
                action.required = False
    parser.set_defaults(**selected, _defaults=defaults)
