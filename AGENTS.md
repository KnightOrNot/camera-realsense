# Repository Guidelines

## Structure and Responsibilities

`src/camera_realsense/` contains device discovery, capture, processing, preview, experiments and CLI configuration. `stream.py` provides reusable RGB-D packets with SDK timestamp provenance and calibration. `config/default.toml` governs standalone CLI defaults; integrating applications pass their own API settings. `tests/` contains offline unittest regressions; `docs/` explains usage and reference behavior.

Keep robot control, application recording and LeRobot conversion in their owning repositories. Preserve original Z16 depth, depth scale, independent stream clocks and camera calibration. Do not replace timestamps with frame numbers or silently treat device hardware time as host monotonic time. Importing an API must not open a device.

## Development Commands

Use Python 3.11 and uv from this repository root:

- `uv sync --frozen`: synchronize the standalone environment.
- `uv run --frozen pyright`: check types using local SDK stubs.
- `uv run --frozen python -m unittest discover -s tests -v`: run offline tests.
- `uv run camera-realsense info --profiles`: inspect a connected camera before selecting profiles.
- `uv build`: build distributions.

## Style and Validation

Use four spaces, snake_case functions/modules, PascalCase classes and annotated public interfaces. Keep tests in `test_*.py`. No coverage threshold is configured. Preserve existing style; avoid formatting unrelated modules. Exercise timeouts, stream deduplication, invalid time domains, original depth values and resource cleanup. Cross-repository data changes also require controller RGB-D conversion/readback tests. Offline tests do not establish USB stability or hardware synchronization accuracy.

## Contributions

Use concise conventional commit subjects. Describe behavior, checks, affected consumers and hardware-validation status. Update README, docs, CONTRIBUTING and CHANGELOG when interfaces change. Do not commit captures, environments or caches. Preserve LICENSE, which currently records that no project license has been chosen. Publish tested submodule commits before a parent repository references them.
