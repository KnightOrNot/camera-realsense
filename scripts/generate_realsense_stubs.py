"""Generate editor-only stubs from the installed RealSense binary's real API."""

from __future__ import annotations

import logging
import re
from importlib.metadata import version
from pathlib import Path

from pybind11_stubgen import CLIArgs, arg_parser, run, stub_parser_from_args
from pybind11_stubgen.printer import Printer
from pybind11_stubgen.structs import Value
from pybind11_stubgen.writer import Writer


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    root = Path(__file__).resolve().parents[1]
    args = arg_parser().parse_args(
        ["pyrealsense2", "--numpy-array-remove-parameters", "--enum-class-locations",
         "^(format|extension|calib_location)$:pyrealsense2.pyrealsense2"],
        namespace=CLIArgs(),
    )
    parser = stub_parser_from_args(args)
    parse_annotation = parser.parse_annotation_str
    parse_value = parser.parse_value_str

    def normalize_annotation(annotation: str):
        annotation = annotation.strip()
        # Some binding docstrings expose C++ names instead of Python names.
        annotation = re.sub(r"rs2::([a-z_]+)", r"pyrealsense2.pyrealsense2.\1", annotation)
        annotation = annotation.replace("pyrealsense2.pyrealsense2.frameset",
                                        "pyrealsense2.pyrealsense2.composite_frame")
        if annotation in ("json", "pyrealsense2.pyrealsense2.embedded_close_range_filter"):
            # JSON is heterogeneous; the latter native type is not exported by this binary.
            annotation = "typing.Any"  # The SDK's JSON values are heterogeneous.
        return parse_annotation(annotation)

    def normalize_value(value: str):
        value = value.strip()
        # An opaque native instance is a valid default, but not a Python expression.
        if re.fullmatch(r"<pyrealsense2\.[\w.]+ object at 0x[0-9a-fA-F]+>", value):
            return Value(repr="...", is_print_safe=True)
        return parse_value(value)

    setattr(parser, "parse_annotation_str", normalize_annotation)
    setattr(parser, "parse_value_str", normalize_value)
    target = root / "typings"
    run(parser, Printer(invalid_expr_as_ellipses=True), ["pyrealsense2"], str(target), root_suffix=None,
        dry_run=False, writer=Writer(stub_ext="pyi"))
    header = (f"# Generated from pyrealsense2 {version('pyrealsense2')} using pybind11-stubgen.\n"
              "# Regenerate: uv run python scripts/generate_realsense_stubs.py\n")
    for path in (target / "pyrealsense2").rglob("*.pyi"):
        path.write_text(header + path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Generated RealSense stubs in {target}")


if __name__ == "__main__":
    main()
