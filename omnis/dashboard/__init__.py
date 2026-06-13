"""Single-page dashboard served by the Python standard library."""

from omnis.dashboard.payload import build_dashboard_data, filter_requirements
from omnis.dashboard.server import render_page, serve, write_static

__all__ = [
    "build_dashboard_data",
    "filter_requirements",
    "render_page",
    "write_static",
    "serve",
]
