"""Experiment artifact writers; no camera access is performed here."""

from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .diagnostics import log
from .models import ImageSnapshot


def output_path(label: str, suffix: str = "") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path("captures") / f"{label}_{stamp}{suffix}"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_ply(path: Path, vertices: np.ndarray, colors: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(vertices)}\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    data = np.empty(len(vertices), dtype=[("xyz", "<f4", (3,)), ("rgb", "u1", (3,))])
    data["xyz"], data["rgb"] = vertices, colors
    with path.open("wb") as handle:
        handle.write(header.encode("ascii"))
        handle.write(data.tobytes())
    log(f"点云已保存：{path}，{len(vertices)} 点；坐标单位 m。")


def save_images(folder: Path, snapshot: ImageSnapshot) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, raw in snapshot.images.items():
        Image.fromarray(raw).save(folder / f"{name}.png")
        if name == "depth":
            np.save(folder / "depth.npy", raw)
    write_json(folder / "frames.json", snapshot.metadata)
    log(f"图片已保存：{folder}")


@contextmanager
def csv_output(path: Path, columns: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        yield writer


def prepare_recording(path: Path) -> Path:
    if path.suffix.lower() != ".db3":
        raise ValueError("当前 SDK 的录像输出要求 .db3 扩展名，请使用 --output captures/record.db3。")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
