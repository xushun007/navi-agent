from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from .viewer import (
    TraceViewerService,
    render_session_html,
    render_session_index_html,
    render_trace_html,
)


def serve_trace_viewer(
    service: TraceViewerService,
    *,
    port: int = 8765,
    session_limit: int = 100,
) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("trace viewer port must be between 1 and 65535")
    handler = _handler(service, session_limit=session_limit)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"trace_viewer_url: http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler(service: TraceViewerService, *, session_limit: int):
    class TraceViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/":
                self._html(render_session_index_html(service.list_sessions(limit=session_limit)))
                return
            if path.startswith("/session/"):
                session = service.get_session(unquote(path.removeprefix("/session/")))
                if session is None:
                    self._not_found()
                    return
                self._html(render_session_html(session))
                return
            if path.startswith("/trace/"):
                trace = service.get_trace(unquote(path.removeprefix("/trace/")))
                if trace is None:
                    self._not_found()
                    return
                self._html(render_trace_html(trace))
                return
            self._not_found()

        def log_message(self, format: str, *args) -> None:
            return

        def _html(self, content: str, *, status: int = 200) -> None:
            body = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _not_found(self) -> None:
            self._html(
                '<!doctype html><meta charset="utf-8"><h1>Not found</h1>',
                status=404,
            )

    return TraceViewerHandler
