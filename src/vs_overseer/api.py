from __future__ import annotations

from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any


@dataclass
class ControlBridge:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    stop_requested: bool = False
    safe_pause: bool = False
    safe_pause_reason: str = ""
    health_payload: dict[str, Any] = field(default_factory=dict)
    summary_payload: dict[str, Any] = field(default_factory=dict)

    def request_stop(self) -> None:
        with self._lock:
            self.stop_requested = True

    def request_pause(self, reason: str) -> None:
        with self._lock:
            self.safe_pause = True
            self.safe_pause_reason = reason.strip() or "manual_pause"

    def request_resume(self) -> None:
        with self._lock:
            self.safe_pause = False
            self.safe_pause_reason = ""

    def consume_stop(self) -> bool:
        with self._lock:
            return bool(self.stop_requested)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stop_requested": bool(self.stop_requested),
                "safe_pause": bool(self.safe_pause),
                "safe_pause_reason": self.safe_pause_reason,
            }

    def update_health(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.health_payload = dict(payload)

    def update_summary(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.summary_payload = dict(payload)

    def get_health(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.health_payload)

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.summary_payload)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _handler_factory(bridge: ControlBridge):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, bridge.get_health())
                return
            if self.path == "/summary/latest":
                self._send(200, bridge.get_summary())
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/control/stop":
                bridge.request_stop()
                self._send(200, {"ok": True, "action": "stop"})
                return
            if self.path == "/control/pause":
                payload = _read_json_body(self)
                reason = str(payload.get("reason", "manual_pause"))
                bridge.request_pause(reason)
                self._send(200, {"ok": True, "action": "pause", "reason": reason})
                return
            if self.path == "/control/resume":
                bridge.request_resume()
                self._send(200, {"ok": True, "action": "resume"})
                return
            self._send(404, {"error": "not_found"})

        def log_message(self, format: str, *args: Any) -> None:
            _ = format
            _ = args
            return

    return Handler


def start_api_server(bridge: ControlBridge, *, host: str = "127.0.0.1", port: int = 8787) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), _handler_factory(bridge))
    thread = threading.Thread(target=server.serve_forever, name="control-api", daemon=True)
    thread.start()
    return server, thread
