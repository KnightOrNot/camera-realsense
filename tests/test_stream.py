"""Clock and stream lifecycle tests without initializing a physical device."""

import unittest
import time
from types import SimpleNamespace

import numpy as np
from unittest.mock import Mock, patch

from camera_realsense.stream import ClockBridge, ColorStream


class ClockTests(unittest.TestCase):
    def map(self, clock, timestamp=1000.0, domain="global_time", **changes):
        values = dict(
            wall_ns=1_000_000_000, before_ns=5_000_000_000, after_ns=5_000_000_100
        )
        values.update(changes)
        return clock.map(timestamp, domain, **values)

    def test_maps_system_epoch_to_host_monotonic_and_records_uncertainty(self):
        timestamp, offset, uncertainty = self.map(ClockBridge())
        self.assertEqual(timestamp, 5_000_000_050)
        self.assertEqual(offset, 4_000_000_050)
        self.assertEqual(uncertainty, 100)

    def test_hardware_clock_cannot_be_compared_to_robot_clock(self):
        with self.assertRaisesRegex(ValueError, "Unaligned"):
            self.map(ClockBridge(), domain="hardware_clock")

    def test_rejects_clock_steps_and_backwards_camera_time(self):
        clock = ClockBridge()
        self.map(clock)
        with self.assertRaisesRegex(RuntimeError, "stepped"):
            self.map(clock, wall_ns=2_000_000_000)
        with self.assertRaisesRegex(RuntimeError, "strictly increasing"):
            self.map(clock)

    def test_rejects_late_future_and_nonfinite_timestamps(self):
        for timestamp in (0, 1100.0):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(RuntimeError):
                    self.map(ClockBridge(), timestamp)
        with self.assertRaises(ValueError):
            self.map(ClockBridge(), float("nan"))

    def test_slow_clock_sampling_is_not_silently_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "sampling"):
            self.map(ClockBridge(), after_ns=5_010_000_000)

    def test_close_is_idempotent_and_does_not_open_a_device(self):
        stream = ColorStream()
        pipe = Mock()
        stream._pipe = pipe
        stream.close()
        stream.close()
        pipe.stop.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "not started"):
            stream.read()

    def test_stream_rejects_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            ColorStream(width=0)


class PacketTests(unittest.TestCase):
    def packet(self, stream, name, number, image, domain="global_time"):
        frame = Mock()
        frame.get_frame_number.return_value = number
        frame.get_frame_timestamp_domain.return_value = SimpleNamespace(name=domain)
        frame.get_timestamp.return_value = time.time_ns() / 1e6 - 10
        frame.get_data.return_value = image
        return stream._packet(frame, name)

    def test_rgb_and_depth_counters_clocks_and_owned_buffers_are_independent(self):
        stream = ColorStream(
            width=2,
            height=2,
            depth_width=2,
            depth_height=2,
            warmup_frames=0,
            depth_enabled=True,
        )
        rgb = np.full((2, 2, 3), 120, np.uint8)
        depth = np.array([[0, 65535], [1000, 2000]], np.uint16)
        self.assertIsNone(self.packet(stream, "color", 10, rgb))
        depth_packet = self.packet(stream, "depth", 1, depth)
        color_packet = stream._pending.popleft()
        assert color_packet is not None and depth_packet is not None
        self.assertEqual(depth_packet.stream, "depth")
        self.assertEqual(depth_packet.image.dtype, np.uint16)
        self.assertEqual(int(depth_packet.image[0, 1]), 65535)
        depth[:] = 0
        rgb[:] = 0
        self.assertEqual(int(depth_packet.image[1, 1]), 2000)
        self.assertEqual(int(color_packet.image[0, 0, 0]), 120)
        self.assertIsNone(self.packet(stream, "depth", 1, depth))
        with self.assertRaisesRegex(RuntimeError, "counter reset"):
            self.packet(stream, "color", 9, rgb)

    def test_per_stream_warmup_and_hardware_domain_never_emit_unaligned_frames(self):
        stream = ColorStream(width=2, height=2, warmup_frames=1)
        rgb = np.zeros((2, 2, 3), np.uint8)
        self.assertIsNone(self.packet(stream, "color", 1, rgb))
        self.assertIsNone(self.packet(stream, "color", 2, rgb, "hardware_clock"))
        self.assertIsNone(self.packet(stream, "color", 3, rgb))
        self.assertIsNotNone(self.packet(stream, "color", 4, rgb))

    def test_startup_counter_reset_restarts_the_full_warmup(self):
        stream = ColorStream(width=2, height=2, warmup_frames=2)
        rgb = np.zeros((2, 2, 3), np.uint8)
        for number in (100, 101, 1, 2):
            self.assertIsNone(self.packet(stream, "color", number, rgb))
        packet = self.packet(stream, "color", 3, rgb)
        assert packet is not None
        self.assertEqual(packet.frame_number, 3)
        self.assertIn("restarts=1", stream.startup_status)
        with self.assertRaisesRegex(
            RuntimeError, "phase=streaming.*previous=3, current=1"
        ):
            self.packet(stream, "color", 1, rgb)

    def test_depth_reset_discards_color_candidates_before_joint_readiness(self):
        stream = ColorStream(
            width=2,
            height=2,
            depth_width=2,
            depth_height=2,
            depth_enabled=True,
            warmup_frames=1,
        )
        rgb = np.zeros((2, 2, 3), np.uint8)
        depth = np.full((2, 2), 1234, np.uint16)
        for name, number, image in (
            ("color", 100, rgb),
            ("color", 101, rgb),
            ("depth", 100, depth),
            ("depth", 1, depth),
            ("depth", 2, depth),
            ("color", 1, rgb),
        ):
            self.assertIsNone(self.packet(stream, name, number, image))
        packet = self.packet(stream, "color", 2, rgb)
        assert packet is not None
        self.assertEqual(packet.frame_number, 2)
        self.assertEqual(
            [(p.stream, p.frame_number) for p in stream._pending], [("depth", 2)]
        )
        with self.assertRaisesRegex(
            RuntimeError, "depth frame counter reset.*phase=streaming"
        ):
            self.packet(stream, "depth", 1, depth)

    def test_running_timestamp_domain_change_remains_fatal(self):
        stream = ColorStream(width=2, height=2, warmup_frames=0)
        rgb = np.zeros((2, 2, 3), np.uint8)
        self.assertIsNotNone(self.packet(stream, "color", 1, rgb))
        with self.assertRaisesRegex(RuntimeError, "domain changed.*phase=streaming"):
            self.packet(stream, "color", 2, rgb, "system_time")

    def test_clock_mapping_failure_can_recover_only_before_first_output(self):
        stream = ColorStream(width=2, height=2, warmup_frames=0)
        rgb = np.zeros((2, 2, 3), np.uint8)
        with patch.object(
            ClockBridge, "map", side_effect=RuntimeError("clock stepped")
        ):
            self.assertIsNone(self.packet(stream, "color", 1, rgb))
        self.assertIsNotNone(self.packet(stream, "color", 2, rgb))
        with patch.object(
            ClockBridge, "map", side_effect=RuntimeError("clock stepped")
        ):
            with self.assertRaisesRegex(RuntimeError, "clock stepped.*phase=streaming"):
                self.packet(stream, "color", 3, rgb)


if __name__ == "__main__":
    unittest.main()
