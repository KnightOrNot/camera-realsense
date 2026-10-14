#!/usr/bin/env python3
"""RealSense D455f 实时预览窗口（Tkinter + pyrealsense2）。

依赖在 venv 里**全部已就绪**，无需安装：
    pyrealsense2 2.58.3 / numpy 2.3.5 / Pillow 12.3.0 / tkinter (Tk 9.0)

用法
----
# 本会话若未带上 video 组（usermod 后需新会话），用 sg 借用：
sg video -c ".venv/bin/python realsense/realsense_view.py"

# 新开的 WSL 会话里组已生效，可直接跑：
.venv/bin/python realsense/realsense_view.py

# 排障：只枚举设备与全部可用流，不开窗口（不需要 DISPLAY）
sg video -c ".venv/bin/python realsense/realsense_view.py --probe"

# 自检：不开窗口，抓 30 帧并报实测帧率 + 存一张样例图
sg video -c ".venv/bin/python realsense/realsense_view.py --capture 30"

# 点云：一开窗就是点云视图（还可按 p 存 PLY）
sg video -c ".venv/bin/python realsense/realsense_view.py --rotate 180 --cloud"

# 点云：免窗口导出一份 PLY + 一张渲染预览图
sg video -c ".venv/bin/python realsense/realsense_view.py --save-ply realsense/snapshots/cloud.ply"

按键
----
    q / Esc    退出
    d          视图循环：彩色 → 深度 → 点云
    ← → ↑ ↓    点云视角：左右转 / 上下转
    + / -      点云缩放        r  视角复位
    p          把当前点云存成 PLY（MeshLab / CloudCompare 能直接开）
    s          存一张快照 PNG 到 snapshots/
    空格       暂停 / 继续
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import pyrealsense2 as rs
except ImportError:  # pragma: no cover
    sys.exit(
        "缺少 pyrealsense2。装包请用：\n"
        "  uv pip install --python .venv/bin/python pyrealsense2"
    )

HERE = Path(__file__).resolve().parent
SNAPSHOT_DIR = HERE / "snapshots"  # 与其他相机资料同放 realsense/ 下

# 按优先级尝试的流参数（相机在 USB 2.0 上，高分辨率很可能起不来 → 逐个回退）
COLOR_CANDIDATES = [
    (640, 480, 30),
    (640, 480, 15),
    (640, 480, 6),
    (848, 480, 30),
    (424, 240, 30),
    (1280, 720, 30),
    (1920, 1080, 30),
]
DEPTH_CANDIDATES = [
    (640, 480, 30),
    (640, 480, 15),
    (480, 270, 30),
    (480, 270, 15),
    (848, 480, 30),
    (1280, 720, 30),
]
# --both：深度与彩色同时开，取两者共同支持的分辨率
BOTH_CANDIDATES = [
    (640, 480, 30),
    (848, 480, 30),
    (640, 480, 15),
    (480, 270, 30),
]


def frame_of(frameset, stream):
    """从 frameset 里安全取某个流；没有则返回 None（不抛异常）。"""
    try:
        f = frameset.get_color_frame() if stream == rs.stream.color else frameset.get_depth_frame()
    except RuntimeError:
        return None
    return f if f else None


def colorize_depth(depth_frame, max_depth: int) -> np.ndarray:
    d = np.clip(np.asanyarray(depth_frame.get_data()), 0, max_depth)  # uint16，单位 mm
    d8 = (d.astype(np.float32) * (255.0 / max_depth)).astype(np.uint8)
    return DEPTH_LUT[d8]


def orient(img: np.ndarray, rotate: int, mirror: bool) -> np.ndarray:
    """相机装反了就靠这个摆正：先左右镜像，再旋转。"""
    if mirror:
        img = img[:, ::-1]
    if rotate == 90:
        img = np.rot90(img, 1)
    elif rotate == 180:
        img = np.rot90(img, 2)
    elif rotate == 270:
        img = np.rot90(img, 3)
    return np.ascontiguousarray(img)


def make_depth_lut() -> np.ndarray:
    """256 级伪彩 LUT（远=冷色，近=暖色），只算一次。"""
    x = np.arange(256)
    stops = [0, 32, 96, 160, 224, 255]
    r = np.interp(x, stops, [0, 0, 0, 255, 255, 255])
    g = np.interp(x, stops, [0, 0, 255, 255, 128, 255])
    b = np.interp(x, stops, [128, 255, 255, 0, 0, 255])
    return np.stack([r, g, b], axis=1).astype(np.uint8)


DEPTH_LUT = make_depth_lut()


# --------------------------------------------------------------------------- #
# 点云：构建 / 渲染 / 导出（纯 numpy，零新依赖）
# --------------------------------------------------------------------------- #
CLOUD_MAX_POINTS = 120_000  # 渲染前抽稀上限；再多 CPU 光栅化就掉帧了
CLOUD_FOV_DEG = 60.0        # 点云渲染的虚拟视场角
MODE_NAMES = {"color": "彩色", "depth": "深度", "cloud": "点云"}


def _as_mat(buf, cols: int) -> np.ndarray:
    """realsense 的 buffer → (N, cols) float32（不同版本有的给扁平有的给矩阵）。"""
    a = np.asanyarray(buf)
    if a.dtype != np.float32:
        a = a.view(np.float32)
    return a.reshape(-1, cols)


def build_cloud(frames, max_depth_mm: float = 3000.0):
    """一帧 RGB-D → 带真实颜色的点云。

    返回 `(verts (N,3) float32 米, colors (N,3) uint8 RGB)`；取不到返回 `(None, None)`。

    步骤：深度 **align 到彩色帧**（否则两个镜头的视差会让颜色错位）→ `map_to` 彩色
    → `calculate` 得到顶点与纹理坐标 → 按纹理坐标回查彩色图，取每个点的真实颜色。

    坐标系沿用 RealSense 相机系：**x 右、y 下、z 前**，单位米。
    """
    try:
        aligned = rs.align(rs.stream.color).process(frames)
        df = aligned.get_depth_frame()
        cf = aligned.get_color_frame()
    except RuntimeError:
        df = cf = None
    if not df or not cf:  # 对齐失败（比如没开彩色流）就退回未对齐的原始帧
        df = frames.get_depth_frame()
        cf = frames.get_color_frame()
        if not df or not cf:
            return None, None

    pc = rs.pointcloud()
    pc.map_to(cf)
    points = pc.calculate(df)
    verts = _as_mat(points.get_vertices(), 3)
    tex = _as_mat(points.get_texture_coordinates(), 2)

    color_img = np.asanyarray(cf.get_data())[:, :, ::-1]  # bgr8 → RGB
    ch, cw = color_img.shape[:2]
    u = np.clip((tex[:, 0] * cw).astype(np.int32), 0, cw - 1)
    v = np.clip((tex[:, 1] * ch).astype(np.int32), 0, ch - 1)
    colors = np.ascontiguousarray(color_img[v, u])

    # 无效深度在 z16 里是 0 → 顶点会落到原点，按距离裁掉
    z = verts[:, 2]
    keep = np.isfinite(z) & (z > 0.05) & (z < max_depth_mm / 1000.0)
    verts, colors = verts[keep], colors[keep]
    if len(verts) == 0:
        return None, None
    return verts, colors


def subsample(verts, colors, limit: int = CLOUD_MAX_POINTS):
    """等间隔抽稀到 limit 个点以内（点云原始 30 万点，直接画会卡）。"""
    if len(verts) <= limit:
        return verts, colors
    step = int(np.ceil(len(verts) / limit))
    return verts[::step], colors[::step]


def fit_distance(verts, fov_deg: float = CLOUD_FOV_DEG) -> float:
    """让点云主体大致填满视野所需的相机距离（米）。

    取「到点云中心距离的**中位数**」，不用高分位：深度图里总散着到 2–3 m 开外
    的零星噪点，高分位会被它们撑大好几倍，结果主体缩成画面正中一小坨
    （实测同一帧：中位 0.30 m，90 分位 2.64 m —— 差 9 倍）。
    """
    r = float(np.median(np.linalg.norm(verts - np.median(verts, axis=0), axis=1)))
    return max(r * 1.15 / np.tan(np.radians(fov_deg) / 2.0), 0.08)


def render_cloud(verts, colors, *, yaw=0.0, pitch=0.0, dist=None,
                 size=(640, 480), fov_deg=CLOUD_FOV_DEG, splat=2) -> np.ndarray:
    """把点云光栅化成一张 RGB 图（CPU 画家算法，零依赖）。

    先绕点云质心转 `yaw`/`pitch`，再沿 +z 推到相机前 `dist` 米处做针孔投影；
    然后**远→近**依次覆盖写入（画家算法），近处的点自然盖住远处的。
    `splat` 让每个点铺成 splat×splat 的小方块，否则单像素会有密密麻麻的洞。
    """
    W, H = size
    img = np.zeros((H, W, 3), np.uint8)
    if verts is None or len(verts) == 0:
        return img

    p = (verts - np.median(verts, axis=0)).astype(np.float32)
    if dist is None:
        dist = fit_distance(verts, fov_deg)

    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]], np.float32)
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    p = p @ (Ry @ Rx).T
    p[:, 2] += dist

    z = p[:, 2]
    f = (H / 2.0) / np.tan(np.radians(fov_deg) / 2.0)
    u = np.full(len(p), -1.0, np.float32)
    v = np.full(len(p), -1.0, np.float32)
    ok = z > 1e-3
    u[ok] = f * p[ok, 0] / z[ok] + W / 2.0
    v[ok] = f * p[ok, 1] / z[ok] + H / 2.0
    ok &= (u >= 0) & (u < W) & (v >= 0) & (v < H)
    if not ok.any():
        return img

    order = np.argsort(z[ok])[::-1]  # 远 → 近
    ui = u[ok][order].astype(np.int32)
    vi = v[ok][order].astype(np.int32)
    ci = colors[ok][order]

    buf = img.reshape(-1, 3)
    for dy in range(splat):
        for dx in range(splat):
            yy, xx = vi + dy, ui + dx
            m = (yy < H) & (xx < W)
            buf[yy[m] * W + xx[m]] = ci[m]
    return img


def save_ply(path, verts, colors) -> int:
    """写二进制小端 PLY（MeshLab / CloudCompare / Open3D 都能直接开）。"""
    n = len(verts)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment generated by realsense_view.py\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n"
    )
    rec = np.empty(n, dtype=np.dtype([
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("red", "u1"), ("green", "u1"), ("blue", "u1"),
    ]))
    rec["x"], rec["y"], rec["z"] = verts[:, 0], verts[:, 1], verts[:, 2]
    rec["red"], rec["green"], rec["blue"] = colors[:, 0], colors[:, 1], colors[:, 2]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(header.encode("ascii"))
        fh.write(rec.tobytes())
    return n


# --------------------------------------------------------------------------- #
# --probe：枚举设备与流
# --------------------------------------------------------------------------- #
def dev_info(dev, key: str, default: str = "?") -> str:
    try:
        return str(dev.get_info(getattr(rs.camera_info, key)))
    except Exception:
        return default


def probe() -> int:
    ctx = rs.context()
    devs = ctx.query_devices()
    print(f"RealSense 设备数：{len(devs)}")

    if not devs:
        print(
            "\n找不到设备。依次排查：\n"
            "  1. 相机是否 attach 进 WSL：   lsusb | grep 8086\n"
            "  2. 设备节点是否存在：         ls /dev/video*\n"
            "  3. 权限（最常见）：           id -nG | grep -q video || echo '不在 video 组'\n"
            "     → 本会话临时借用：sg video -c \"...\"\n"
            "     → 永久修复：      sudo usermod -aG video gyx（需新会话，或 sg 借用）"
        )
        return 1

    for i, dev in enumerate(devs):
        print(f"\n[{i}] {dev_info(dev, 'name')}")
        print(f"    serial      : {dev_info(dev, 'serial_number')}")
        print(f"    firmware    : {dev_info(dev, 'firmware_version')}")
        print(f"    USB 类型    : {dev_info(dev, 'usb_type_descriptor')}   ← 2.x 表示跑在 USB 2.0")
        print(f"    物理端口    : {dev_info(dev, 'physical_port')}")

        for sensor in dev.sensors:
            print(f"\n    传感器: {dev_info(sensor, 'name')}")
            profiles = sensor.get_stream_profiles()
            seen = set()
            for p in profiles:
                try:
                    v = p.as_video_stream_profile()
                    key = (p.stream_type().name, p.format().name, v.width(), v.height(), p.fps())
                except RuntimeError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
            for stream, fmt, w, h, fps in sorted(seen, key=lambda k: (k[0], -k[2] * k[3], -k[4], k[1])):
                print(f"        {stream:<10} {fmt:<8} {w:>4}x{h:<5} @{fps:<3} fps")

        show_calibration(dev)
    return 0


def show_calibration(dev) -> None:
    """读内参/外参 —— 「点云能不能做」的关键验证。

    标定由 HWMC 命令接口读取；在 Linux/V4L2 后端上，HWMC 正是通过
    **UVC 扩展单元（XU）的控制传输**实现的，因此这一步通了，点云才有戏。
    """
    print("\n    —— 标定读取测试（点云的前提）——")
    first = {}
    for sensor in dev.sensors:
        for p in sensor.get_stream_profiles():
            try:
                v = p.as_video_stream_profile()
            except RuntimeError:
                continue
            first.setdefault(v.stream_type(), v)

    for st in (rs.stream.depth, rs.stream.color):
        v = first.get(st)
        if v is None:
            continue
        try:
            i = v.get_intrinsics()
            model = getattr(i.model, "name", str(i.model))
            print(f"      {st.name:<6} 内参 ✅ {i.width}x{i.height}  "
                  f"fx={i.fx:.2f} fy={i.fy:.2f} ppx={i.ppx:.2f} ppy={i.ppy:.2f}  {model}")
        except Exception as exc:
            print(f"      {st.name:<6} 内参 ❌ {exc}")

    if rs.stream.depth in first and rs.stream.color in first:
        try:
            e = first[rs.stream.depth].get_extrinsics_to(first[rs.stream.color])
            tx, ty, tz = (x * 1000 for x in e.translation)  # 米 → 毫米
            print(f"      depth→color 外参 ✅ 基线 = ({tx:.1f}, {ty:.1f}, {tz:.1f}) mm")
        except Exception as exc:
            print(f"      depth→color 外参 ❌ {exc}")


# --------------------------------------------------------------------------- #
# 起流（带参数回退）
# --------------------------------------------------------------------------- #
def start_pipeline(color_on: bool, depth_on: bool, want):
    if want:
        candidates = [(want[0], want[1], want[2])]
    elif color_on and depth_on:
        candidates = BOTH_CANDIDATES
    elif depth_on:
        candidates = DEPTH_CANDIDATES
    else:
        candidates = COLOR_CANDIDATES

    errors = []
    for w, h, fps in candidates:
        cfg = rs.config()
        if color_on:
            cfg.enable_stream(rs.stream.color, w, h, rs.format.bgr8, fps)
        if depth_on:
            cfg.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps)
        pipe = rs.pipeline()
        try:
            profile = pipe.start(cfg)
        except RuntimeError as exc:
            errors.append(f"  {w}x{h}@{fps}: {exc}")
            try:
                pipe.stop()
            except Exception:
                pass
            continue
        print(f"✓ 已起流 {w}x{h}@{fps}  (color={color_on}, depth={depth_on})")
        return pipe, profile, (w, h, fps)

    print("所有候选参数都起不来：")
    print("\n".join(errors))
    raise SystemExit(
        "\n若报「No device connected」或权限相关错误 → 多半是 video 组问题，\n"
        '试试：sg video -c ".venv/bin/python realsense/realsense_view.py"'
    )


def actual_profile(profile, stream_type) -> str:
    try:
        v = profile.get_stream(stream_type).as_video_stream_profile()
        return f"{v.width()}x{v.height()}@{v.fps()}"
    except Exception:
        return "?"


# --------------------------------------------------------------------------- #
# 预览窗口
# --------------------------------------------------------------------------- #
class Viewer:
    def __init__(self, args, pipe, profile, size):
        import tkinter as tk
        from PIL import Image, ImageTk

        self.tk, self.Image, self.ImageTk = tk, Image, ImageTk
        self.pipe = pipe
        self.args = args
        self.mode = "cloud" if args.cloud else ("depth" if args.depth else "color")
        self.max_depth = args.max_depth
        self.paused = False
        self._photo = None  # 必须持引用，否则被 GC 掉画面就空白
        self._last_rgb = None
        self._running = True
        self._t0 = time.time()
        self._frames = 0
        self._fps = 0.0
        # 当前实际开着哪些流：color / depth / both（按 d 会自动升到 both）
        self._streams = "both" if (args.both or args.cloud) else ("depth" if args.depth else "color")
        self._apply_size(size)
        # 点云状态
        self.cloud_pts = (None, None)  # (verts, colors)
        self._cloud_t = 0.0            # 上次重建点云的时刻（重建有成本，限速）
        self._cloud_dist = None        # 自动适配的相机距离
        self.yaw = 0.0
        self.pitch = 0.0
        self.zoom = 1.0

        self.root = tk.Tk()
        self.root.title("RealSense D455f 预览")
        self.label = tk.Label(self.root, bg="black")
        self.label.pack()
        self.status = tk.Label(self.root, anchor="w", font=("monospace", 9))
        self.status.pack(fill="x")
        self.root.bind("<Key>", self.on_key)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        # WSLg 下新窗口不一定自动拿到键盘焦点；不抢焦点的话按键会全部丢掉
        self.root.focus_force()

        print(self._key_help())
        self.status.configure(text=self._status_text())
        self.root.after(0, self.tick)

    # -- 尺寸 / 状态栏文案 ------------------------------------------------- #
    def _apply_size(self, size):
        w, h = size[0], size[1]
        self.raw_size = (w, h)  # 流的原始尺寸；点云渲染按它出图，再统一走 orient()
        # 旋转 90/270 会让画面宽高互换，显示尺寸要跟着换
        self.src_w, self.src_h = (h, w) if self.args.rotate in (90, 270) else (w, h)
        # 显示尺寸：等比缩放到 --display-width
        if self.args.display_width and self.args.display_width != self.src_w:
            scale = self.args.display_width / self.src_w
            self.disp_size = (self.args.display_width, max(1, int(round(self.src_h * scale))))
        else:
            self.disp_size = (self.src_w, self.src_h)

    def _key_help(self) -> str:
        first = {"color": "d 切到深度（会自动补开深度流）",
                 "depth": "d 切到点云",
                 "cloud": "d 回到彩色"}[self.mode]
        return (f"窗口已开。按键：q/Esc 退出 | {first} | ←→↑↓ 转点云 | +/- 缩放 | "
                "r 复位视角 | p 存点云PLY | s 存快照 | 空格 暂停\n"
                "若按键没反应，先用鼠标点一下窗口（焦点问题）。")

    def _status_text(self) -> str:
        if self.mode == "cloud":
            n = 0 if self.cloud_pts[0] is None else len(self.cloud_pts[0])
            view = f"点云 {n} 点  yaw {np.degrees(self.yaw):+5.0f}° pitch {np.degrees(self.pitch):+5.0f}°  ×{self.zoom:.2f}"
        else:
            view = "深度" if self.mode == "depth" else "彩色"
        return (f"{view} {self.src_w}x{self.src_h}  显示 {self.disp_size[0]}x{self.disp_size[1]}"
                f"  {self._fps:5.1f} fps   d切视图 ←→↑↓转 +/-缩放 r复位 p存PLY s快照 q退出")

    def cycle_mode(self):
        """彩色 → 深度 → 点云 → 彩色。进深度/点云前先把深度流补上。"""
        if self._streams != "both" and not self.enable_both():
            print("⚠️ 深度流不可用，只能停在彩色视图")
            return
        order = ["color", "depth", "cloud"]
        self.mode = order[(order.index(self.mode) + 1) % len(order)]
        print(f"→ {MODE_NAMES[self.mode]} 视图")
        self.status.configure(text=self._status_text())

    # -- 点云 -------------------------------------------------------------- #
    def cloud_image(self, frames):
        """按当前视角渲染点云；点云本身限速重建（约 7 Hz）。"""
        now = time.time()
        if now - self._cloud_t > 0.15:
            self._cloud_t = now
            verts, colors = build_cloud(frames, self.max_depth)
            if verts is not None and colors is not None:
                self.cloud_pts = subsample(verts, colors)
                self._cloud_dist = fit_distance(self.cloud_pts[0])
        verts, colors = self.cloud_pts
        if verts is None:
            return None  # 还没建好 → render() 会临时退回彩色画面
        return render_cloud(verts, colors, yaw=self.yaw, pitch=self.pitch,
                            dist=(self._cloud_dist or 1.0) / self.zoom, size=self.raw_size)

    def save_cloud_ply(self):
        verts, colors = self.cloud_pts
        if verts is None:
            print("（点云还没生成，先等画面出来）")
            return
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        path = SNAPSHOT_DIR / datetime.now().strftime("rs_cloud_%Y%m%d_%H%M%S.ply")
        n = save_ply(path, verts, colors)
        print(f"点云已存：{path}（{n} 点，可直接拖进 MeshLab / CloudCompare 看）")

    # -- 动态补开深度流 ---------------------------------------------------- #
    def _restart(self, color_on: bool, depth_on: bool):
        """停掉当前流，按新配置重开（同一设备不能开两条 pipeline）。"""
        if self.pipe is not None:
            try:
                self.pipe.stop()
            except Exception:
                pass
        return start_pipeline(color_on, depth_on, self.args.profile)

    def enable_both(self) -> bool:
        """把流升到「彩色 + 深度」；失败则回退原配置并返回 False。"""
        if self._streams == "both":
            return True
        was_depth = self._streams == "depth"
        try:
            pipe, _profile, size = self._restart(True, True)
        except SystemExit as exc:
            print(f"⚠️ 开深度流失败，回退：{exc}")
            try:
                self.pipe, _p, size = self._restart(not was_depth, was_depth)
            except SystemExit:
                self.quit()
                return False
            return False
        self.pipe, self._streams = pipe, "both"
        self._apply_size(size)
        print("→ 已补开深度流")
        return True

    # -- 按键 ------------------------------------------------------------- #
    def on_key(self, event):
        k = event.keysym.lower()
        if k in ("q", "escape"):
            self.quit()
        elif k == "d":
            self.cycle_mode()
        elif k in ("left", "right", "up", "down"):
            if self.mode != "cloud":
                return
            if k == "left":
                self.yaw -= 0.12
            elif k == "right":
                self.yaw += 0.12
            elif k == "up":
                self.pitch -= 0.12
            else:
                self.pitch += 0.12
        elif k in ("plus", "equal", "kp_add"):
            self.zoom = min(self.zoom * 1.15, 8.0)
        elif k in ("minus", "underscore", "kp_subtract"):
            self.zoom = max(self.zoom / 1.15, 0.2)
        elif k == "r":
            self.yaw = self.pitch = 0.0
            self.zoom = 1.0
            print("视角已复位")
        elif k == "p":
            self.save_cloud_ply()
        elif k == "s":
            self.snapshot()
        elif k == "space":
            self.paused = not self.paused
            print("已暂停" if self.paused else "继续")

    def snapshot(self):
        if self._last_rgb is None:
            return
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        name = datetime.now().strftime("rs_%Y%m%d_%H%M%S.png")
        path = SNAPSHOT_DIR / name
        self.Image.fromarray(self._last_rgb).save(path)
        print(f"快照已存：{path}")

    # -- 主循环 ----------------------------------------------------------- #
    def tick(self):
        if not self._running:
            return
        try:
            if not self.paused:
                frames = self.pipe.poll_for_frames()
                if frames:
                    self.render(frames)
        except RuntimeError as exc:
            print(f"取帧出错：{exc}")
        self.root.after(5, self.tick)

    def render(self, frames):
        rgb = None
        if self.mode == "cloud":
            rgb = self.cloud_image(frames)
        elif self.mode == "depth":
            df = frame_of(frames, rs.stream.depth)
            if df:
                rgb = colorize_depth(df, self.max_depth)
        if rgb is None:
            cf = frame_of(frames, rs.stream.color)
            if not cf:
                return
            rgb = np.asanyarray(cf.get_data())[:, :, ::-1]  # BGR → RGB

        rgb = orient(rgb, self.args.rotate, self.args.mirror)
        self._last_rgb = rgb

        im = self.Image.fromarray(rgb)
        if (rgb.shape[1], rgb.shape[0]) != self.disp_size:
            im = im.resize(self.disp_size, self.Image.Resampling.BILINEAR)
        self._photo = self.ImageTk.PhotoImage(im)
        self.label.configure(image=self._photo)

        self._frames += 1
        dt = time.time() - self._t0
        if dt >= 0.5:
            self._fps = self._frames / dt
            self._frames, self._t0 = 0, time.time()
            self.status.configure(text=self._status_text())

    def quit(self):
        self._running = False
        try:
            self.pipe.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def capture(args) -> int:
    """免窗口自检：抓 N 帧，报实测帧率与抖动，并存一张样例图。"""
    color_on = not args.depth
    depth_on = args.depth or args.both
    pipe, profile, size = start_pipeline(color_on, depth_on, args.profile)
    dev = profile.get_device()
    print(f"设备: {dev_info(dev, 'name')}  序列号 {dev_info(dev, 'serial_number')}"
          f"  USB {dev_info(dev, 'usb_type_descriptor')}")

    stamps, sample = [], None
    n_color = n_depth = 0
    t0 = time.time()
    try:
        while len(stamps) < args.capture:
            fs = pipe.wait_for_frames(5000)
            stamps.append(time.time())
            cf = frame_of(fs, rs.stream.color)
            df = frame_of(fs, rs.stream.depth)
            if cf:
                n_color += 1
                # 取【最后】一帧：开头几帧自动曝光/白平衡还没收敛，颜色会偏
                sample = orient(np.asanyarray(cf.get_data())[:, :, ::-1], args.rotate, args.mirror)
            if df:
                n_depth += 1
                if not cf:
                    sample = orient(colorize_depth(df, args.max_depth), args.rotate, args.mirror)
    finally:
        pipe.stop()

    dt = time.time() - t0
    n = len(stamps)
    print(f"\n取到 {n} 帧，用时 {dt:.2f}s → 平均 {n / dt:.1f} fps")
    print(f"color 帧 {n_color} / depth 帧 {n_depth}")
    if n > 1:
        gaps = np.diff(stamps) * 1000
        med = float(np.median(gaps))
        print(f"帧间隔中位 {med:.1f} ms，最大 {gaps.max():.1f} ms"
              f"（最大/中位 = {gaps.max() / med:.1f}x，越接近 1 越稳）")

    if sample is not None:
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        path = SNAPSHOT_DIR / datetime.now().strftime("rs_test_%Y%m%d_%H%M%S.png")
        Image.fromarray(sample).save(path)
        print(f"\n样例图: {path}")
        print(f"像素统计: mean={sample.mean():6.1f} std={sample.std():6.1f} "
              f"min={sample.min():3d} max={sample.max():3d}  （全 0 = 没真正取到画面）")
    return 0


def save_ply_cmd(args) -> int:
    """免窗口：抓一帧 → 生成点云 → 存 PLY，并存一张渲染预览 PNG。"""
    pipe, profile, size = start_pipeline(True, True, args.profile)
    dev = profile.get_device()
    print(f"设备: {dev_info(dev, 'name')}  USB {dev_info(dev, 'usb_type_descriptor')}")

    frames = None
    try:
        for _ in range(max(1, args.ply_warmup)):  # 先丢几帧，等自动曝光/深度收敛
            frames = pipe.wait_for_frames(5000)
        verts, colors = build_cloud(frames, args.max_depth)
    finally:
        pipe.stop()

    if verts is None or colors is None:
        print("没拿到有效点云：深度可能整帧无效，或彩色流没起来")
        return 1

    z = verts[:, 2]
    print(f"点云 {len(verts)} 点；深度 {z.min() * 1000:.0f}–{z.max() * 1000:.0f} mm"
          f"（中位 {np.median(z) * 1000:.0f} mm）")
    print(f"包围盒 {np.ptp(verts[:, 0]) * 1000:.0f} × {np.ptp(verts[:, 1]) * 1000:.0f}"
          f" × {np.ptp(z) * 1000:.0f} mm；颜色均值 RGB = {np.round(colors.mean(axis=0), 1)}")

    n = save_ply(args.save_ply, verts, colors)
    print(f"\n点云已存：{args.save_ply}（{n} 点，MeshLab / CloudCompare / Open3D 可直接打开）")

    prev = Path(args.save_ply).with_suffix(".preview.png")
    img = render_cloud(*subsample(verts, colors), yaw=0.25, pitch=-0.2, size=size[:2])
    Image.fromarray(img).save(prev)
    print(f"渲染预览：{prev}（斜 25° 视角；空白=没点或被裁掉，可调 --max-depth）")
    return 0


def run_viewer(args) -> int:
    if args.cloud:
        color_on = depth_on = True
    else:
        color_on = not args.depth
        depth_on = args.depth or args.both
    pipe, profile, size = start_pipeline(color_on, depth_on, args.profile)

    dev = profile.get_device()
    print(f"设备: {dev_info(dev, 'name')}  序列号 {dev_info(dev, 'serial_number')}")
    print(f"USB 类型: {dev_info(dev, 'usb_type_descriptor')}   (2.x = 跑在 USB 2.0，带宽受限)")
    if color_on:
        print(f"彩色流: {actual_profile(profile, rs.stream.color)}")
    if depth_on:
        print(f"深度流: {actual_profile(profile, rs.stream.depth)}")

    Viewer(args, pipe, profile, size).root.mainloop()
    return 0


# --------------------------------------------------------------------------- #
def parse_args():
    p = argparse.ArgumentParser(
        description="RealSense 实时预览（Tkinter + pyrealsense2）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--probe", action="store_true", help="只枚举设备/流，不开窗口")
    p.add_argument("--capture", type=int, metavar="N",
                   help="免窗口自检：抓 N 帧，报帧率/抖动并存一张样例图")
    p.add_argument("--depth", action="store_true", help="只开深度流（伪彩显示）")
    p.add_argument("--both", action="store_true",
                   help="启动时就把深度+彩色都开（不加也行：按 d 会自动补开）")
    p.add_argument("--cloud", action="store_true",
                   help="启动即点云视图（等价于按两次 d；同样会自动开深度+彩色）")
    p.add_argument("--save-ply", metavar="PATH",
                   help="免窗口：抓一帧生成点云存成 PLY，并存一张渲染预览 PNG")
    p.add_argument("--ply-warmup", type=int, default=30,
                   help="--save-ply 前先丢弃的帧数（等自动曝光/深度收敛）")
    p.add_argument("--profile", nargs=3, type=int, metavar=("W", "H", "FPS"),
                   help="强制指定分辨率帧率，如 --profile 640 480 15")
    p.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270),
                   help="画面旋转（相机装反了就用 180）")
    p.add_argument("--mirror", action="store_true", help="画面左右镜像")
    p.add_argument("--max-depth", type=int, default=3000, help="深度伪彩上限（mm）")
    p.add_argument("--display-width", type=int, default=960,
                   help="窗口内显示宽度（原图仍按流分辨率存快照）；0 = 不缩放")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.probe:
        return probe()
    if args.capture:
        return capture(args)
    if args.save_ply:
        return save_ply_cmd(args)
    if args.both and args.depth:
        print("--both 与 --depth 同时给出；按 --both 处理")
        args.depth = False
    return run_viewer(args)


if __name__ == "__main__":
    raise SystemExit(main())
