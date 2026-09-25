"""A stand-in for api.previouslyon.gg, just the calls the app makes, on a
local port, so sign-in and sync run over real HTTP in the tests."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "device-token-1"


class FakeApi:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}  # (game, file name) -> bytes
        self.retention_days: int | None = 30
        self.approve_after = 1  # token polls answered "pending" before approval
        self.deny = False
        self.polls = 0
        self.revoked = False
        self.full = False  # answer uploads with 413 account_full
        self.extra_sessions: list[dict] = []  # raw manifest entries, as a broken or hostile server might send
        self.calls: list[tuple[str, str]] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status: int, body: bytes | dict, ctype: str = "application/json") -> None:
                data = json.dumps(body).encode() if isinstance(body, dict) else body
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _authed(self) -> bool:
                if api.revoked or self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._send(401, {"detail": "device signed out"})
                    return False
                return True

            def do_POST(self):
                api.calls.append(("POST", self.path))
                body = json.loads(self._body() or b"{}")
                if self.path == "/v1/device/code":
                    api.device_name = body["device_name"]
                    return self._send(200, {"device_code": "dc", "user_code": "BCDF-GHJK",
                                            "verification_uri_complete": "https://previouslyon.gg/link?code=BCDF-GHJK",
                                            "interval": 0, "expires_in": 600})
                if self.path == "/v1/device/token":
                    api.polls += 1
                    if api.deny:
                        return self._send(400, {"error": "access_denied"})
                    if api.polls <= api.approve_after:
                        return self._send(400, {"error": "authorization_pending"})
                    return self._send(200, {"token": TOKEN, "device_id": "d1", "account": "player@example.com"})
                self._send(404, {"detail": "no"})

            def do_DELETE(self):
                api.calls.append(("DELETE", self.path))
                if self.path == "/v1/device" and self._authed():
                    api.revoked = True
                    self._send(200, {"ok": True})

            def do_GET(self):
                api.calls.append(("GET", self.path))
                if not self._authed():
                    return
                m = re.fullmatch(r"/v1/sync/(\w+)(?:/(.+))?", self.path)
                game, name = m.group(1), m.group(2)
                if name is None:
                    sessions: dict[str, dict] = {}
                    for (g, n), data in api.files.items():
                        if g != game:
                            continue
                        stamp, _, kind = n.partition(".")
                        key = "log_sha256" if kind == "jsonl" else "recap_sha256"
                        sessions.setdefault(stamp, {"stamp": stamp, "log_sha256": None, "recap_sha256": None})[
                            key] = hashlib.sha256(data).hexdigest()
                    listed = sorted(sessions.values(), key=lambda s: s["stamp"]) + api.extra_sessions
                    return self._send(200, {"retention_days": api.retention_days, "sessions": listed})
                data = api.files.get((game, name))
                self._send(200, data, "application/octet-stream") if data is not None else self._send(404, {})

            def do_PUT(self):
                api.calls.append(("PUT", self.path))
                data = self._body()
                if not self._authed():
                    return
                if api.full:
                    return self._send(413, {"detail": {"error": "account_full", "max_bytes": 100 * 1024 * 1024,
                                                       "max_sessions": 1000}})
                _, _, _, game, name = self.path.split("/")
                api.files[(game, name)] = data
                self._send(200, {"stored": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)
