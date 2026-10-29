"""RGB/depth frames with SDK provenance and a shared host monotonic clock."""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoFrame:
    """Owned image: RGB uint8 or native Z16 depth; stream distinguishes them."""

    image: np.ndarray
    timestamp_ns: int
    received_time_ns: int
    sdk_timestamp_ms: float
    sdk_timestamp_domain: str
    frame_number: int
    clock_offset_ns: int
    clock_uncertainty_ns: int
    stream: str = "color"


class ClockBridge:
    """Map SDK host-correlated milliseconds without assuming a shared epoch."""

    def __init__(self) -> None:
        self._offset: int | None = None
        self._previous: int | None = None

    def map(
        self,
        timestamp_ms: float,
        domain: str,
        *,
        wall_ns: int,
        before_ns: int,
        after_ns: int,
    ) -> tuple[int, int, int]:
        if domain not in {"global_time", "system_time"}:
            raise ValueError(f"Unaligned RealSense timestamp domain: {domain}")
        if not math.isfinite(timestamp_ms) or timestamp_ms < 0:
            raise ValueError("Invalid RealSense timestamp")
        if after_ns < before_ns or after_ns - before_ns > 5_000_000:
            raise RuntimeError("Host clock sampling took more than 5 ms")
        offset = (before_ns + after_ns) // 2 - wall_ns
        if self._offset is not None and abs(offset - self._offset) > 5_000_000:
            raise RuntimeError("System clock stepped; camera alignment is invalid")
        mapped = round(timestamp_ms * 1_000_000) + offset
        if mapped > after_ns + 50_000_000 or after_ns - mapped > 1_000_000_000:
            raise RuntimeError("RealSense timestamp is outside the host clock window")
        if self._previous is not None and mapped <= self._previous:
            raise RuntimeError("RealSense timestamps are not strictly increasing")
        self._offset, self._previous = offset, mapped
        return mapped, offset, after_ns - before_ns


def _intrinsics(profile: Any) -> dict[str, Any]:
    intr = profile.as_video_stream_profile().get_intrinsics()
    return {
        "fx": intr.fx,
        "fy": intr.fy,
        "ppx": intr.ppx,
        "ppy": intr.ppy,
        "model": intr.model.name,
        "coeffs": list(intr.coeffs),
    }


class ColorStream:
    """Bounded-poll RGB or RGB-D acquisition, without devices opened on import.

    RGB-D yields independently timestamped color/depth packets. Depth retains its
    native viewpoint and Z16 values; no spatial resampling or colorization occurs.
    """

    def __init__(
        self,
        *,
        serial: str = "",
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        warmup_frames: int = 15,
        depth_enabled: bool = False,
        depth_width: int = 640,
        depth_height: int = 480,
        depth_fps: int = 30,
        mode: str = "manual",
    ) -> None:
        if any(
            type(v) is not int or v <= 0
            for v in (width, height, fps, depth_width, depth_height, depth_fps)
        ):
            raise ValueError("width, height and fps must be positive integers")
        if type(warmup_frames) is not int or warmup_frames < 0:
            raise ValueError("warmup_frames must be non-negative")
        if type(depth_enabled) is not bool:
            raise ValueError("depth_enabled must be boolean")
        if mode not in {"manual", "auto", "fast", "slow"}:
            raise ValueError("mode must be manual, auto, fast or slow")
        self.mode = mode
        self.serial, self.width, self.height, self.fps = serial, width, height, fps
        self.depth_enabled = depth_enabled
        self.depth_width, self.depth_height, self.depth_fps = (
            depth_width,
            depth_height,
            depth_fps,
        )
        self.warmup_frames = warmup_frames
        self.metadata: dict[str, Any] = {}
        self._pipe: Any = None
        self._restore: list[tuple[Any, float]] = []
        self._last_number: dict[str, int] = {}
        self._counts: dict[str, int] = {}
        self._bridges: dict[str, ClockBridge] = {}
        self._pending: deque[VideoFrame] = deque()
        self._domains: dict[str, str] = {}
        self._timestamps: dict[str, float] = {}
        self._startup_packets: dict[str, VideoFrame] = {}
        self._startup_complete = False
        self._startup_resets = 0
        self._last_startup_reset = ""

    @property
    def startup_status(self) -> str:
        streams = ("color", "depth") if self.depth_enabled else ("color",)
        counts = ", ".join(
            f"{name}={self._counts.get(name, 0)}/{self.warmup_frames}"
            for name in streams
        )
        phase = "streaming" if self._startup_complete else "startup"
        return (
            f"phase={phase}, warmup({counts}), restarts={self._startup_resets}, "
            f"last_restart={self._last_startup_reset or 'none'}"
        )

    def _clear_tracking(self) -> None:
        self._last_number.clear()
        self._counts.clear()
        self._bridges.clear()
        self._pending.clear()
        self._domains.clear()
        self._timestamps.clear()
        self._startup_packets.clear()

    def _restart_startup(self, reason: str) -> None:
        # No packet has been delivered: both streams must requalify together.
        self._clear_tracking()
        self._startup_resets += 1
        self._last_startup_reset = reason
        logger.warning("%s; restarting camera startup warmup", reason)

    def _frame_diagnostic(
        self, stream: str, number: int, timestamp_ms: float, domain: str
    ) -> str:
        phase = "streaming" if self._startup_complete else "startup"
        return (
            f"stream={stream}, phase={phase}, "
            f"previous={self._last_number.get(stream)}, current={number}, "
            f"previous_timestamp_ms={self._timestamps.get(stream)}, "
            f"timestamp_ms={timestamp_ms}, "
            f"previous_domain={self._domains.get(stream)}, domain={domain}, "
            f"warmup_count={self._counts.get(stream, 0)}, "
            f"warmup_frames={self.warmup_frames}"
        )

    def start(self) -> ColorStream:
        if self._pipe is not None:
            raise RuntimeError("ColorStream is already started")
        if self.mode == "manual":
            return self._start_profile()
        original = (
            self.width,
            self.height,
            self.fps,
            self.depth_width,
            self.depth_height,
            self.depth_fps,
        )
        profiles = (
            []
            if self.mode == "slow"
            else [
                (640, 360, 90, 640, 360, 90),
                (640, 360, 60, 640, 360, 60),
            ]
        )
        profiles.append((original[0], original[1], 30, original[3], original[4], 30))
        failures = []
        for profile in profiles:
            (
                self.width,
                self.height,
                self.fps,
                self.depth_width,
                self.depth_height,
                self.depth_fps,
            ) = profile
            try:
                self._start_profile()
                rates = self._probe_rates()
                expected = {"color": self.fps}
                if self.depth_enabled:
                    expected["depth"] = self.depth_fps
                if any(
                    rates.get(name, 0) < fps * 0.85 for name, fps in expected.items()
                ):
                    raise RuntimeError(f"received FPS below 85% of profile: {rates}")
                self.metadata["profile_selection"] = {
                    "requested_mode": self.mode,
                    "measured_fps": rates,
                    "rejected": failures,
                }
                return self
            except Exception as exc:
                failures.append(str(exc))
                self.close()
        (
            self.width,
            self.height,
            self.fps,
            self.depth_width,
            self.depth_height,
            self.depth_fps,
        ) = original
        raise RuntimeError(f"no camera profile passed startup probing: {failures}")

    def _probe_rates(self) -> dict[str, float]:
        arrivals: dict[str, list[float]] = {}
        latest: dict[str, VideoFrame] = {}
        expected = {"color", "depth"} if self.depth_enabled else {"color"}
        deadline = time.monotonic() + 10
        started = None
        while time.monotonic() < deadline:
            frame = self.read(timeout_s=0.2)
            if frame is None:
                continue
            now = time.monotonic()
            arrivals.setdefault(frame.stream, []).append(now)
            latest[frame.stream] = frame
            if started is None and set(latest) == expected:
                started = now
            if started is not None and now - started >= 1.0:
                rates = {
                    name: (len(times) - 1) / (times[-1] - times[0])
                    for name, times in arrivals.items()
                    if len(times) >= 2 and times[-1] > times[0]
                }
                self._pending.clear()
                self._pending.extend(latest.values())
                return rates
        raise TimeoutError(f"camera profile probe timed out: {self.startup_status}")

    def _start_profile(self) -> ColorStream:
        import pyrealsense2 as rs

        from .capture import configure_video
        from .device import device_info, get_sensor, select_device
        from .models import VideoConfig

        if self._pipe is not None:
            raise RuntimeError("ColorStream is already started")
        self._clear_tracking()
        self._startup_complete = False
        self._startup_resets = 0
        self._last_startup_reset = ""
        device = select_device(self.serial or None)
        try:
            for name in ["color", "depth"] if self.depth_enabled else ["color"]:
                sensor = get_sensor(device, name)
                if sensor.supports(rs.option.global_time_enabled):
                    self._restore.append(
                        (sensor, sensor.get_option(rs.option.global_time_enabled))
                    )
                    sensor.set_option(rs.option.global_time_enabled, 1.0)
            config, _ = configure_video(
                VideoConfig(
                    width=self.depth_width,
                    height=self.depth_height,
                    fps=self.depth_fps,
                    color_width=self.width,
                    color_height=self.height,
                    color_fps=self.fps,
                ),
                device,
                "rgbd" if self.depth_enabled else "color",
            )
            pipe = rs.pipeline()
            profile = pipe.start(config)
            self._pipe = pipe
            self.metadata = {
                "device": device_info(device),
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "pixel_format": "rgb8",
                "clock": "time.monotonic_ns",
                "timestamp_source": "realsense_global_or_system_time",
                "intrinsics": _intrinsics(profile.get_stream(rs.stream.color)),
                "profile_selection": {"requested_mode": self.mode, "measured_fps": {}},
            }
            if self.depth_enabled:
                depth = profile.get_stream(rs.stream.depth)
                extr = depth.get_extrinsics_to(profile.get_stream(rs.stream.color))
                units = device.first_depth_sensor().get_depth_scale()
                if not math.isfinite(units) or units <= 0:
                    raise RuntimeError("Invalid RealSense depth scale")
                self.metadata["depth"] = {
                    "width": self.depth_width,
                    "height": self.depth_height,
                    "fps": self.depth_fps,
                    "pixel_format": "z16",
                    "depth_units_m": units,
                    "intrinsics": _intrinsics(depth),
                    "spatial_alignment": "native_depth",
                    "depth_to_color": {
                        "rotation": list(extr.rotation),
                        "translation_m": list(extr.translation),
                    },
                }
            return self
        except BaseException as exc:
            try:
                self.close()
            except Exception as cleanup_error:
                exc.add_note(f"Camera cleanup also failed: {cleanup_error}")
            raise

    def _packet(self, frame: Any, stream: str) -> VideoFrame | None:
        if not frame:
            return None
        number = frame.get_frame_number()
        previous = self._last_number.get(stream)
        if number == previous:
            return None
        domain = frame.get_frame_timestamp_domain().name
        timestamp_ms = frame.get_timestamp()
        diagnostic = self._frame_diagnostic(stream, number, timestamp_ms, domain)
        if domain not in {"hardware_clock", "global_time", "system_time"}:
            raise ValueError(
                f"Unaligned RealSense timestamp domain: {domain}; {diagnostic}"
            )
        if not math.isfinite(timestamp_ms) or timestamp_ms < 0:
            raise ValueError(f"Invalid RealSense timestamp; {diagnostic}")
        discontinuity = ""
        if previous is not None and number < previous:
            discontinuity = f"RealSense {stream} frame counter reset"
        elif stream in self._domains and domain != self._domains[stream]:
            discontinuity = f"RealSense {stream} timestamp domain changed"
        if discontinuity:
            reason = f"{discontinuity}; {diagnostic}"
            if self._startup_complete:
                raise RuntimeError(reason)
            self._restart_startup(reason)
        self._last_number[stream] = number
        self._domains[stream] = domain
        self._timestamps[stream] = timestamp_ms
        self._counts[stream] = self._counts.get(stream, 0) + 1
        if self._counts[stream] <= self.warmup_frames or domain == "hardware_clock":
            return None
        before, wall = time.monotonic_ns(), time.time_ns()
        after = time.monotonic_ns()
        try:
            mapped, offset, uncertainty = self._bridges.setdefault(
                stream, ClockBridge()
            ).map(
                timestamp_ms,
                domain,
                wall_ns=wall,
                before_ns=before,
                after_ns=after,
            )
        except RuntimeError as exc:
            reason = f"{exc}; {diagnostic}"
            if self._startup_complete:
                raise RuntimeError(reason) from exc
            self._restart_startup(reason)
            return None
        image = np.asanyarray(frame.get_data()).copy()
        shape = (
            (self.height, self.width, 3)
            if stream == "color"
            else (self.depth_height, self.depth_width)
        )
        dtype = np.uint8 if stream == "color" else np.uint16
        if image.shape != shape or image.dtype != dtype:
            raise RuntimeError(f"Camera returned an unexpected {stream} image layout")
        packet = VideoFrame(
            image,
            mapped,
            after,
            timestamp_ms,
            domain,
            number,
            offset,
            uncertainty,
            stream,
        )
        if not self._startup_complete:
            self._startup_packets[stream] = packet
            expected = {"color", "depth"} if self.depth_enabled else {"color"}
            if not expected.issubset(self._startup_packets):
                return None
            # Queue the latest counterpart only after both clocks have qualified.
            self._pending.extend(
                value for name, value in self._startup_packets.items() if name != stream
            )
            self._startup_packets.clear()
            self._startup_complete = True
        return packet

    def read(self, timeout_s: float = 0.2) -> VideoFrame | None:
        if self._pipe is None:
            raise RuntimeError("ColorStream is not started")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive and finite")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._pending:
                return self._pending.popleft()
            frames = self._pipe.poll_for_frames()
            if not frames:
                time.sleep(0.002)
                continue
            inputs = [("color", frames.get_color_frame())]
            if self.depth_enabled:
                inputs.append(("depth", frames.get_depth_frame()))
            for name, frame in inputs:
                packet = self._packet(frame, name)
                if packet is not None:
                    self._pending.append(packet)
        return self._pending.popleft() if self._pending else None

    def close(self) -> None:
        pipe, self._pipe = self._pipe, None
        errors = []
        try:
            if pipe is not None:
                pipe.stop()
        finally:
            while self._restore:
                sensor, previous = self._restore.pop()
                try:
                    sensor.set_option(sensor_option_global_time(), previous)
                except Exception as exc:
                    errors.append(exc)
            self._pending.clear()
            self._startup_packets.clear()
            if errors:
                raise RuntimeError(f"Failed to restore camera settings: {errors}")

    def __enter__(self) -> ColorStream:
        return self.start()

    def __exit__(self, *_args: Any) -> None:
        self.close()


def sensor_option_global_time() -> Any:
    import pyrealsense2 as rs

    return rs.option.global_time_enabled
