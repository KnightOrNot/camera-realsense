# Generated from pyrealsense2 2.59.1.11053 using pybind11-stubgen.
# Regenerate: uv run python scripts/generate_realsense_stubs.py
"""
Real User Monitoring (RUM) usage statistics
"""
from __future__ import annotations
__all__: list[str] = ['get_report_path', 'is_cloud_enabled', 'set_cloud_enabled']
def get_report_path() -> str:
    """
    Path of the on-disk RUM report file (read it to inspect or upload the report).
    """
def is_cloud_enabled() -> bool:
    """
    Resolved cloud-upload consent (RS2_RUM_CLOUD_ENABLED env var overrides the config file).
    """
def set_cloud_enabled(enabled: bool) -> None:
    """
    Set the cloud-upload consent flag (persists to the per-user config file).
    """
