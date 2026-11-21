"""Local fake of the Flexen API for the tests: records every request, answers from a queue or a handler. No network."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

import pytest

EXAMPLES: dict[str, Any] = json.loads((Path(__file__).resolve().parents[3] / "contract" / "examples.json").read_text("utf-8"))
OK_HEADERS = {"X-Request-Id": "req_test_1", "X-Credits-Charged": "1", "X-Credits-Remaining": "18341"}
TEST_KEY = "flx_test_0123456789abcdefghijABCDEFGHIJ0123456789xyz"


def error_body(code: str, message: str | None = None, request_id: str = "req_err_1") -> dict[str, Any]:
    return {"error": {"code": code, "message": message or f"message for {code}", "request_id": request_id}}


@dataclass
class Reply:
    status: int = 200
    json: Any = None
    text: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass
class Recorded:
    method: str
    url: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


class Fake:
    def __init__(self) -> None:
        self.requests: list[Recorded] = []
        self._queue: deque[Reply] = deque()
        self._handler: Callable[[Recorded], Reply] | None = None
        self._lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # quiet
                pass

            def _serve(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                u = urlsplit(self.path)
                rec = Recorded(self.command, self.path, u.path, dict(parse_qsl(u.query)), {k.lower(): v for k, v in self.headers.items()}, body)
                with fake._lock:
                    fake.requests.append(rec)
                    if fake._handler is not None:
                        r = fake._handler(rec)
                    elif fake._queue:
                        r = fake._queue.popleft()
                    else:
                        r = Reply(500, error_body("internal_error", "fake: nothing queued"))
                if r.delay:
                    time.sleep(r.delay)
                payload = (json.dumps(r.json) if r.json is not None else (r.text or "")).encode("utf-8")
                try:
                    self.send_response(r.status)
                    for k, v in r.headers.items():
                        self.send_header(k, v)
                    if r.json is not None:
                        self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = do_POST = do_DELETE = _serve

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def queue(self, *replies: Reply) -> None:
        self._queue.extend(replies)

    def handle(self, fn: Callable[[Recorded], Reply]) -> None:
        self._handler = fn

    def reset(self) -> None:
        self.requests.clear()
        self._queue.clear()
        self._handler = None

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture(scope="session")
def _fake_server():
    f = Fake()
    yield f
    f.close()


@pytest.fixture
def fake(_fake_server: Fake) -> Fake:
    _fake_server.reset()
    return _fake_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
