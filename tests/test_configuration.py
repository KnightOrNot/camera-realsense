"""TOML defaults, explicit overrides and configuration errors before camera access."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from camera_realsense import cli, configuration, device
from camera_realsense.models import ExperimentConfig, VideoConfig


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "default.toml"
        self.source = (Path(__file__).parent / "fixtures" / "default.toml").read_text()
        self.path.write_text(self.source)

    def parser(self, source=None):
        self.path.write_text(self.source if source is None else source)
        return cli.build_parser(self.path)

    def test_shared_command_and_explicit_defaults_have_correct_priority(self):
        source = self.source.replace("fps = 5\n", "fps = 30\n")
        source = source.replace("[commands.depth]\n", "[commands.depth]\nfps = 15\n")
        parser = self.parser(source)
        self.assertEqual(parser.parse_args(["color"]).fps, 30)
        self.assertEqual(parser.parse_args(["depth"]).fps, 15)
        self.assertEqual(parser.parse_args(["depth", "--fps", "60"]).fps, 60)
        config = cli.to_experiment_config(parser.parse_args(["depth", "--fps", "60"]))
        self.assertEqual(config.video.fps, 60)
        self.assertEqual(config.video.width, 480)

    def test_explicit_false_and_zero_override_true_and_nonzero_defaults(self):
        source = self.source.replace("preview = false", "preview = true").replace("colored = false", "colored = true")
        source = source.replace("profiles = false", "profiles = true").replace("frames = 0", "frames = 10")
        parser = self.parser(source)
        self.assertTrue(parser.parse_args(["pointcloud"]).colored)
        args = parser.parse_args(["pointcloud", "--no-preview", "--no-colored", "--frames", "0"])
        self.assertFalse(args.preview)
        self.assertFalse(args.colored)
        self.assertEqual(args.frames, 0)
        self.assertFalse(parser.parse_args(["info", "--no-profiles"]).profiles)

    def test_optional_paths_and_serial_can_be_cleared_explicitly(self):
        source = self.source.replace('serial = ""', 'serial = "configured-camera"')
        source = source.replace('output_dir = ""', 'output_dir = "captures/default"')
        parser = self.parser(source)
        args = parser.parse_args(["depth", "--serial", "", "--output-dir", ""])
        self.assertIsNone(args.serial)
        self.assertIsNone(args.output_dir)
        self.assertEqual(parser.parse_args(["depth"]).output_dir, Path("captures/default"))

    def test_color_zero_means_follow_explicit_primary_stream(self):
        source = self.source.replace("color_fps = 0", "color_fps = 15")
        args = self.parser(source).parse_args(["rgbd", "--fps", "30", "--color-fps", "0"])
        config = cli.to_experiment_config(args)
        self.assertEqual(config.video.fps, 30)
        self.assertIsNone(config.video.color_fps)

    def test_zero_duration_from_toml_and_cli_is_unlimited(self):
        parser = self.parser(self.source.replace("duration = 15.0", "duration = 0"))
        for command in ("depth", "imu", "record", "snapshot", "pointcloud"):
            with self.subTest(command=command):
                self.assertEqual(cli.to_experiment_config(parser.parse_args([command])).capture.duration, 0)
                args = parser.parse_args([command, "--duration", "3"])
                self.assertEqual(cli.to_experiment_config(args).capture.duration, 3)
        parser = self.parser()
        self.assertEqual(parser.parse_args(["depth", "--duration", "0"]).duration, 0)

    def test_toml_pixel_becomes_tuple_and_cli_pixel_overrides_it(self):
        parser = self.parser(self.source.replace("pixel = []", "pixel = [10, 20]"))
        self.assertEqual(cli.to_experiment_config(parser.parse_args(["depth"])).video.pixel, (10, 20))
        args = parser.parse_args(["depth", "--pixel", "30", "40"])
        self.assertEqual(cli.to_experiment_config(args).video.pixel, (30, 40))

    def test_configured_required_option_values_can_be_overridden(self):
        source = self.source.replace('option = ""', 'option = "emitter_enabled"').replace('value = ""', 'value = 0')
        parser = self.parser(source)
        args = parser.parse_args(["set-option"])
        self.assertEqual((args.option, args.value), ("emitter_enabled", 0))
        self.assertEqual(parser.parse_args(["set-option", "--value", "1"]).value, 1)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parser().parse_args(["set-option"])

    def test_config_option_works_before_and_after_subcommand(self):
        self.path.write_text(self.source.replace("fps = 5\n", "fps = 30\n"))
        for args in (["--config", str(self.path), "depth"], ["depth", "--config", str(self.path)]):
            with self.subTest(args=args), patch.object(cli, "run_video", return_value=0) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args), 0)
                self.assertEqual(run.call_args.args[0].video.fps, 30)

    def test_help_shows_selected_configuration_values(self):
        parser = self.parser(self.source.replace("fps = 5\n", "fps = 30\n"))
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
            parser.parse_args(["depth", "--help"])
        self.assertIn("default: 30", output.getvalue())
        self.assertIn(str(self.path), output.getvalue())

    def test_bad_configuration_is_rejected_before_opening_camera(self):
        sources = [self.source.replace("fps = 5\n", 'fps = "30"\n'),
                   self.source.replace("fps = 5\n", "fps = true\n"),
                   self.source.replace("duration = 15.0", "duration = inf"),
                   self.source.replace("duration = 15.0", "duration = -1"),
                   self.source.replace("duration = 15.0", "duration = nan"),
                   self.source.replace("timeout_ms = 5000", "timeout_ms = 0"),
                   self.source.replace("pixel = []", "pixel = [10]"),
                   self.source.replace("fps = 5\n", "fpp = 5\n"),
                   self.source.replace("[commands.info]\n", "[commands.info]\nfps = 30\n"),
                   self.source.replace("[capture]", "[caputre]"),
                   self.source.replace("[video]", "[video"),
                   self.source.replace("min_fps_ratio = 0.5", "min_fps_ratio = 2")]
        with patch.object(device, "select_device") as select, contextlib.redirect_stderr(io.StringIO()):
            for source in sources:
                with self.subTest(source=source):
                    self.path.write_text(source)
                    with self.assertRaises(SystemExit) as caught:
                        cli.main(["depth", "--config", str(self.path)])
                    self.assertEqual(caught.exception.code, 2)
            select.assert_not_called()

    def test_missing_config_is_reported_without_camera_access(self):
        with patch.object(device, "select_device") as select, contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit):
                cli.main(["depth", "--config", str(self.path.with_name("missing.toml"))])
        select.assert_not_called()
        self.assertIn("missing.toml", output.getvalue())

    def test_config_changes_are_loaded_on_next_parser_creation(self):
        self.assertEqual(cli.build_parser(self.path).parse_args(["depth"]).fps, 5)
        self.path.write_text(self.source.replace("fps = 5\n", "fps = 30\n"))
        self.assertEqual(cli.build_parser(self.path).parse_args(["depth"]).fps, 30)

    def test_public_models_use_toml_and_command_factory_matches_cli(self):
        self.path.write_text(self.source.replace("fps = 5\n", "fps = 30\n"))
        with patch.object(configuration, "DEFAULT_CONFIG_PATH", self.path):
            self.assertEqual(VideoConfig().fps, 30)
        configured = ExperimentConfig.from_defaults("depth", self.path)
        self.assertEqual(configured.video.width, 480)
        self.assertEqual(configured.video.fps, 30)

    def test_default_config_path_is_independent_of_working_directory(self):
        expected_fps = cli.build_parser().parse_args(["depth"]).fps
        original = Path.cwd()
        try:
            os.chdir(self.temporary.name)
            self.assertEqual(cli.build_parser().parse_args(["depth"]).fps, expected_fps)
        finally:
            os.chdir(original)
