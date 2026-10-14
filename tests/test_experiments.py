"""Offline data-integrity and failure-path checks; no physical camera is required."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pyrealsense2 as rs
from PIL import Image

from camera_realsense import capture, cli, device, diagnostics, experiments, preview, processing, storage
from camera_realsense.models import CaptureConfig, CaptureStats, ExperimentConfig, OutputConfig, VideoConfig


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds


class WatchdogTests(unittest.TestCase):
    def run_capture(self, producer, expected):
        clock = Clock()

        class Pipeline:
            def poll_for_frames(self):
                clock.now += 0.005
                return producer()

        config = CaptureConfig(duration=1, timeout_ms=10, max_timeouts=2)
        with patch.object(capture.time, "monotonic", lambda: clock.now), \
                patch.object(capture.time, "sleep", clock.sleep), \
                contextlib.redirect_stdout(io.StringIO()):
            return capture.collect(Pipeline(), config, lambda frame: frame, expected)

    def test_absent_camera_frames_stop_at_timeout_limit(self):
        stats = self.run_capture(lambda: set(), ["depth"])
        self.assertEqual(stats.reason, "timeout limit")
        self.assertEqual(stats.counts, {"depth": 0})
        self.assertEqual(stats.timeouts, 2)
        self.assertLess(stats.elapsed_s, 0.1)

    def test_live_depth_cannot_hide_a_dead_color_stream(self):
        stats = self.run_capture(lambda: {"depth"}, ["depth", "color"])
        self.assertEqual(stats.reason, "timeout limit")
        self.assertGreater(stats.counts["depth"], 0)
        self.assertEqual(stats.counts["color"], 0)
        self.assertEqual(stats.complete_frames, 0)

    def test_a_few_initial_frames_do_not_pass_a_timed_stability_test(self):
        stats = CaptureStats(counts={"depth": 5}, elapsed_s=6)
        self.assertEqual(diagnostics.slow_streams(stats, {"depth": 5}, 0.5), ["depth"])
        stats.counts["depth"] = 25
        self.assertEqual(diagnostics.slow_streams(stats, {"depth": 5}, 0.5), [])

    def test_option_is_restored_when_interrupted(self):
        class Sensor:
            value = 1
            def supports(self, _): return True
            def is_option_read_only(self, _): return False
            def get_option_range(self, _): return SimpleNamespace(min=0, max=1)
            def get_option(self, _): return self.value
            def set_option(self, _, value): self.value = value

        sensor = Sensor()
        args = cli.build_parser().parse_args([
            "set-option", "--option", "emitter_enabled", "--value", "0",
        ])
        with patch.object(device, "select_device"), patch.object(device, "get_sensor", return_value=sensor), \
                patch.object(capture.time, "sleep", side_effect=KeyboardInterrupt), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                device.set_option(args.option, args.value, serial=args.serial,
                                  sensor_name=args.sensor, restore_after=args.restore_after)
        self.assertEqual(sensor.value, 1)


class PipelineLifetimeTests(unittest.TestCase):
    def test_processing_failure_releases_camera_and_preserves_exception(self):
        pipeline = Mock()
        cfg = rs.config()
        failure = ValueError("processing failed")
        with patch.object(capture.rs, "pipeline", return_value=pipeline):
            with self.assertRaises(ValueError) as caught:
                with capture.pipeline_session(cfg) as (pipe, profile):
                    self.assertIs(pipe, pipeline)
                    self.assertIs(profile, pipeline.start.return_value)
                    raise failure
        self.assertIs(caught.exception, failure)
        pipeline.start.assert_called_once_with(cfg)
        pipeline.stop.assert_called_once_with()

    def test_start_failure_does_not_stop_an_unstarted_pipeline(self):
        pipeline = Mock()
        pipeline.start.side_effect = RuntimeError("start failed")
        with patch.object(capture.rs, "pipeline", return_value=pipeline):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                with capture.pipeline_session(rs.config()):
                    self.fail("failed pipeline must not be yielded")
        pipeline.stop.assert_not_called()

    def test_interrupt_also_releases_camera(self):
        pipeline = Mock()
        with patch.object(capture.rs, "pipeline", return_value=pipeline):
            with self.assertRaises(KeyboardInterrupt):
                with capture.pipeline_session(rs.config()):
                    raise KeyboardInterrupt
        pipeline.stop.assert_called_once_with()


class DepthDataTests(unittest.TestCase):
    def setUp(self):
        self.device = rs.software_device()
        self.sensor = self.device.add_sensor("Synthetic depth")
        stream = rs.video_stream()
        stream.type, stream.index, stream.uid = rs.stream.depth, 0, 1
        # Use a SIMD-friendly size for the SDK's native pointcloud implementation.
        stream.width, stream.height, stream.fps = 16, 16, 5
        stream.bpp, stream.fmt = 2, rs.format.z16
        intr = rs.intrinsics()
        intr.width, intr.height = 16, 16
        intr.ppx, intr.ppy, intr.fx, intr.fy = 0, 0, 1, 1
        intr.model, intr.coeffs = rs.distortion.none, [0] * 5
        stream.intrinsics = intr
        self.profile = self.sensor.add_video_stream(stream)
        self.sensor.add_read_only_option(rs.option.depth_units, 0.001)
        self.queue = rs.frame_queue(4)
        self.sensor.open(self.profile)
        self.sensor.start(self.queue)
        self.raw = np.zeros((16, 16), dtype=np.uint16)
        self.raw[0, 0], self.raw[1, 0], self.raw[-1, -1] = 1000, 2000, 65000
        frame = rs.software_video_frame()
        frame.pixels, frame.stride, frame.bpp = self.raw.data, 32, 2
        frame.timestamp, frame.frame_number = 1, 1
        frame.domain = rs.timestamp_domain.hardware_clock
        frame.profile, frame.depth_units = self.profile.as_video_stream_profile(), 0.001
        self.sensor.on_video_frame(frame)
        self.depth = self.queue.wait_for_frame(1000).as_depth_frame()

    def tearDown(self):
        del self.depth
        self.sensor.stop()
        self.sensor.close()

    def test_saved_depth_preserves_16_bit_values_and_units(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            folder = Path(directory)
            storage.save_images(folder, processing.prepare_snapshot({"depth": self.depth}, 3))
            with Image.open(folder / "depth.png") as image:
                np.testing.assert_array_equal(np.asarray(image), self.raw)
            np.testing.assert_array_equal(np.load(folder / "depth.npy"), self.raw)
            metadata = json.loads((folder / "frames.json").read_text())
            self.assertAlmostEqual(metadata["depth"]["units_m"], 0.001)
            self.assertAlmostEqual(self.depth.get_distance(0, 0), 1)
            preview = np.asarray(Image.open(folder / "depth_preview.png"))
            np.testing.assert_array_equal(preview[0, 1], [0, 0, 0])

    def test_snapshot_preview_continues_after_save_and_deduplicates_frames(self):
        clock = Clock()
        pipe, camera, window = Mock(), Mock(), Mock()
        camera.supports.return_value = False
        pipe.start.return_value.get_streams.return_value = [self.profile]
        frames = SimpleNamespace(first_or_default=lambda _: self.depth)

        def poll():
            clock.now += 0.1
            return frames

        pipe.poll_for_frames.side_effect = poll
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(device, "select_device", return_value=camera), \
                patch.object(capture, "configure_video", return_value=(rs.config(), ["depth"])), \
                patch.object(capture.rs, "pipeline", return_value=pipe), \
                patch.object(preview, "Preview", return_value=window), \
                patch.object(capture.time, "monotonic", lambda: clock.now), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            config = ExperimentConfig(command="snapshot", capture=CaptureConfig(duration=0.6, min_fps_ratio=0),
                                      video=VideoConfig(width=16, height=16),
                                      output=OutputConfig(output_dir=Path(directory), preview=True))
            self.assertEqual(experiments.run_video(config), 0)
            summary = json.loads((Path(directory) / "summary.json").read_text())
            self.assertEqual(summary["reason"], "duration")
            self.assertEqual(summary["counts"], {"depth": 1})
            self.assertGreater(pipe.poll_for_frames.call_count, 1)
            self.assertEqual(window.show.call_count, 1)
            self.assertEqual(len(output.getvalue().splitlines()), 1)
        window.destroy.assert_called_once_with()
        pipe.stop.assert_called_once_with()

    def test_pointcloud_uses_meters_and_rejects_invalid_and_distant_points(self):
        vertices, colors = processing.cloud_arrays(self.depth, None, 3)
        np.testing.assert_allclose(vertices, [[0, 0, 1], [0, 2, 2]], atol=1e-6)
        self.assertEqual(colors.shape, (2, 3))
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / "cloud.ply"
            storage.write_ply(path, vertices, colors)
            header, payload = path.read_bytes().split(b"end_header\n", 1)
            self.assertIn(b"element vertex 2", header)
            records = np.frombuffer(payload, dtype=[("xyz", "<f4", (3,)), ("rgb", "u1", (3,))])
            np.testing.assert_allclose(records["xyz"], vertices)
            np.testing.assert_array_equal(records["rgb"], colors)

    def test_colored_pointcloud_maps_rgb_without_swapping_channels(self):
        sensor = self.device.add_sensor("Synthetic color")
        stream = rs.video_stream()
        stream.type, stream.index, stream.uid = rs.stream.color, 0, 2
        stream.width, stream.height, stream.fps = 16, 16, 5
        stream.bpp, stream.fmt = 3, rs.format.rgb8
        stream.intrinsics = self.profile.as_video_stream_profile().get_intrinsics()
        profile = sensor.add_video_stream(stream)
        transform = rs.extrinsics()
        transform.rotation = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        transform.translation = [0, 0, 0]
        self.profile.register_extrinsics_to(profile, transform)
        queue = rs.frame_queue(4)
        sensor.open(profile)
        sensor.start(queue)
        color = None
        try:
            rgb = np.zeros((16, 16, 3), dtype=np.uint8)
            rgb[0, 0], rgb[1, 0] = [255, 0, 0], [0, 255, 0]
            frame = rs.software_video_frame()
            frame.pixels, frame.stride, frame.bpp = rgb.data, 48, 3
            frame.timestamp, frame.frame_number = 1, 1
            frame.domain = rs.timestamp_domain.hardware_clock
            frame.profile = profile.as_video_stream_profile()
            sensor.on_video_frame(frame)
            color = queue.wait_for_frame(1000).as_video_frame()
            vertices, colors = processing.cloud_arrays(self.depth, color, 3)
            np.testing.assert_allclose(vertices, [[0, 0, 1], [0, 2, 2]], atol=1e-6)
            np.testing.assert_array_equal(colors, [[255, 0, 0], [0, 255, 0]])
        finally:
            color = None
            sensor.stop()
            sensor.close()


if __name__ == "__main__":
    unittest.main()
