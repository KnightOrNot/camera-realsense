"""Profile probing uses fake pipelines; no USB devices are touched."""

import unittest
from unittest.mock import Mock, patch

from camera_realsense.stream import ColorStream


class ProfileTests(unittest.TestCase):
    def test_auto_falls_back_when_depth_cannot_deliver_requested_rate(self):
        stream = ColorStream(mode="auto", depth_enabled=True)
        attempted = []

        def start():
            attempted.append(stream.fps)
            stream.metadata = {"depth": {"depth_units_m": 0.001}}
            return stream

        with (
            patch.object(stream, "_start_profile", side_effect=start),
            patch.object(
                stream,
                "_probe_rates",
                side_effect=[{"color": 90, "depth": 30}, {"color": 59, "depth": 60}],
            ),
            patch.object(stream, "close") as close,
        ):
            self.assertIs(stream.start(), stream)
        self.assertEqual(attempted, [90, 60])
        close.assert_called_once()
        self.assertEqual(
            stream.metadata["profile_selection"]["measured_fps"]["depth"], 60
        )
        self.assertEqual(stream.metadata["depth"]["depth_units_m"], 0.001)

    def test_slow_uses_baseline_dimensions_and_30_fps(self):
        stream = ColorStream(mode="slow", width=848, height=480, fps=60)
        with (
            patch.object(stream, "_start_profile", return_value=stream),
            patch.object(stream, "_probe_rates", return_value={"color": 30}),
        ):
            stream.start()
        self.assertEqual((stream.width, stream.height, stream.fps), (848, 480, 30))

    def test_explicit_manual_profile_never_probes_or_substitutes(self):
        stream = ColorStream(width=424, height=240, fps=15)
        with (
            patch.object(stream, "_start_profile", return_value=stream) as start,
            patch.object(stream, "_probe_rates") as probe,
        ):
            stream.start()
        start.assert_called_once()
        probe.assert_not_called()
        self.assertEqual((stream.width, stream.height, stream.fps), (424, 240, 15))

    def test_all_failed_profiles_restore_requested_values_and_release_resources(self):
        stream = ColorStream(mode="fast", fps=25)
        with (
            patch.object(
                stream, "_start_profile", side_effect=RuntimeError("unsupported")
            ),
            patch.object(stream, "close") as close,
        ):
            with self.assertRaisesRegex(RuntimeError, "no camera profile"):
                stream.start()
        self.assertEqual(close.call_count, 3)
        self.assertEqual(stream.fps, 25)
        stream._pipe = Mock()
        with self.assertRaisesRegex(RuntimeError, "already started"):
            stream.start()

    def test_invalid_mode_is_rejected_before_opening_device(self):
        with self.assertRaises(ValueError):
            ColorStream(mode="unknown")
