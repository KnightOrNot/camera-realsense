"""Capture display correctness, CLI validation and optional window lifetime."""

import contextlib
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from camera_realsense import cli, device, diagnostics, preview
from camera_realsense.models import CaptureStats


class Terminal(io.StringIO):
    def isatty(self):
        return True


class CaptureStatusTests(unittest.TestCase):
    def test_rgbd_reports_actual_profiles_and_independent_new_frame_rates(self):
        status = diagnostics.CaptureStatus("rgbd", io.StringIO())
        status.set_profiles([{"stream": "depth", "width": 480, "height": 270},
                             {"stream": "color", "width": 424, "height": 240}])
        stats = CaptureStats(counts={"depth": 0, "color": 0})
        diagnostics.display_capture_status(status, stats, 0, True)
        stats.counts.update(depth=30, color=15)
        diagnostics.display_capture_status(status, stats, 1, True)
        self.assertEqual(status.fps, {"depth": 30, "color": 15})
        self.assertIn("mode=rgbd", status.text())
        self.assertIn("depth=480x270@30.0fps", status.text())
        self.assertIn("rgb=424x240@15.0fps", status.text())

    def test_stalled_stream_rate_falls_to_zero(self):
        status = diagnostics.CaptureStatus("rgbd", io.StringIO())
        stats = CaptureStats(counts={"depth": 0, "color": 0})
        status.refresh(stats, 0, True)
        stats.counts.update(depth=30, color=30)
        status.refresh(stats, 1, True)
        stats.counts["depth"] = 60
        status.refresh(stats, 2, True)
        self.assertEqual(status.fps, {"depth": 30, "color": 0})

    def test_terminal_refresh_overwrites_one_row_and_finishes_once(self):
        stream = Terminal()
        with patch.object(diagnostics.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))):
            with diagnostics.status_session("color", stream) as status:
                status.set_profiles([{"stream": "color", "width": 640, "height": 480}])
                status.refresh(CaptureStats(counts={"color": 0}), 0, True)
                diagnostics.log("超时提示" * 40)
                status.refresh(CaptureStats(counts={"color": 15}), 1, True)
        output = stream.getvalue()
        self.assertEqual(output.count("\n"), 1)
        self.assertGreaterEqual(output.count("\r\x1b[2K"), 3)
        for line in output.split("\r\x1b[2K")[1:]:
            cells = sum(2 if ord(char) > 127 else 1 for char in line.rstrip("\n"))
            self.assertLessEqual(cells, 79)
        self.assertIn("mode=rgb", output)
        self.assertIn("@15.0fps", output)

    def test_redirected_output_is_one_final_line_and_nested_status_is_shared(self):
        stream = io.StringIO()
        with diagnostics.status_session("depth", stream) as status:
            with diagnostics.status_session("depth") as nested:
                self.assertIs(nested, status)
                diagnostics.log("saved\nfile")
                status.outcome = "PASS"
                status.set_profiles([{"stream": "depth", "width": 640, "height": 480}])
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        self.assertNotIn("\r", stream.getvalue())
        self.assertNotIn("\x1b", stream.getvalue())
        self.assertIn("saved file", stream.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as normal_output:
            diagnostics.log("normal log")
        self.assertEqual(normal_output.getvalue(), "normal log\n")

    def test_cli_capture_failure_is_reported_on_same_row(self):
        stream = io.StringIO()
        with patch.object(device, "select_device", side_effect=RuntimeError("camera unavailable")), \
                contextlib.redirect_stdout(stream):
            result = cli.main(["depth", "--duration", "1"])
        self.assertEqual(result, 2)
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        self.assertIn("ERROR", stream.getvalue())
        self.assertIn("camera unavailable", stream.getvalue())


class PreviewTests(unittest.TestCase):
    def test_disabled_preview_does_not_create_a_window_or_read_images(self):
        with patch.object(preview, "Preview") as factory:
            with preview.preview_session(False) as window:
                self.assertIsNone(window)
                preview.show_preview(window, {"depth": Mock()})
        factory.assert_not_called()

    def test_preview_window_is_destroyed_on_processing_error(self):
        window = Mock()
        with patch.object(preview, "Preview", return_value=window):
            with self.assertRaisesRegex(ValueError, "processing failed"):
                with preview.preview_session(True) as active:
                    self.assertIs(active, window)
                    raise ValueError("processing failed")
        window.destroy.assert_called_once_with()

    def test_shared_preview_preserves_rgb_and_infrared_and_colorizes_depth(self):
        window = Mock()
        rgb = np.array([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
        ir = np.array([[0, 255]], dtype=np.uint8)
        depth = np.array([[0, 1000]], dtype=np.uint16)
        frames = {name: SimpleNamespace(get_data=lambda raw=raw: raw, get_units=lambda: 0.001)
                  for name, raw in [("depth", depth), ("color", rgb), ("infrared", ir)]}
        preview.show_preview(window, frames, max_depth=3)
        images = window.show.call_args.args[0]
        np.testing.assert_array_equal(images[0][0, 0], [0, 0, 0])
        self.assertEqual(images[0].shape, (1, 2, 3))
        np.testing.assert_array_equal(images[1], rgb)
        np.testing.assert_array_equal(images[2], ir)


class ArgumentValidationTests(unittest.TestCase):
    def test_invalid_capture_parameters_fail_before_opening_camera(self):
        cases = [["depth", "--frames", "-1"], ["depth", "--warmup-frames", "-1"],
                 ["depth", "--min-fps-ratio", "nan"], ["depth", "--min-fps-ratio", "1.1"],
                 ["imu", "--duration", "inf"], ["depth", "--timeout-ms", "0"],
                 ["depth", "--duration", "-1"], ["depth", "--duration", "nan"],
                 ["set-option", "--option", "exposure", "--value", "nan"],
                 ["set-option", "--option", "exposure", "--value", "1", "--restore-after", "-1"]]
        with patch.object(device, "select_device") as select, contextlib.redirect_stderr(io.StringIO()):
            for arguments in cases:
                with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as caught:
                    cli.main(arguments)
                self.assertEqual(caught.exception.code, 2)
            select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
