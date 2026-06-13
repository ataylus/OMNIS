"""Tiny stdlib web server for the OMNIS dashboard.

No third-party server dependency. It computes both benches' payloads once at
startup, inlines them into the page (so the served HTML is fully self-contained),
and also exposes GET /api/payload returning the same JSON. The page is built to
work three ways: inlined data, the /api endpoint, or a static dashboard_data.json
sibling, so a screenshot never depends on the server being up.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from omnis.dashboard.payload import build_dashboard_data

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
# Sentinels in index.html that we replace at serve time.
_INJECT_SENTINEL = "const OMNIS_DATA = null;"
_BENCH_SENTINEL = 'let bench = "sample";'


def render_page(data: dict, initial_bench: str = "sample") -> str:
    """Return index.html with the dashboard data inlined as OMNIS_DATA."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    payload = json.dumps(data).replace("</", "<\\/")  # guard against </script>
    html = html.replace(_INJECT_SENTINEL, f"const OMNIS_DATA = {payload};")
    if initial_bench == "synthetic":
        html = html.replace(_BENCH_SENTINEL, 'let bench = "synthetic";')
    return html


def write_static(data: dict, out_dir: str | Path, initial_bench: str = "sample") -> tuple[Path, Path]:
    """Write a self-contained index.html plus dashboard_data.json to out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "index.html"
    json_path = out / "dashboard_data.json"
    html_path.write_text(render_page(data, initial_bench), encoding="utf-8")
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return html_path, json_path


def _make_handler(data: dict, initial_bench: str = "sample"):
    page = render_page(data, initial_bench)
    page_bytes = page.encode("utf-8")
    api_bytes = json.dumps(data).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(page_bytes, "text/html; charset=utf-8")
            elif path == "/api/payload":
                self._send(api_bytes, "application/json; charset=utf-8")
            else:
                self.send_error(404, "Not found")

        def log_message(self, *args) -> None:  # keep the console quiet
            pass

    return Handler


def serve(port: int = 8000, initial_bench: str = "sample", policies: Path | None = None) -> None:
    """Build the payload and serve the dashboard until interrupted."""
    data = build_dashboard_data(policies) if policies else build_dashboard_data()
    handler = _make_handler(data, initial_bench)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"OMNIS dashboard on http://127.0.0.1:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
