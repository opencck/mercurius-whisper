"""The HTTP side: GET /health (open), GET /v1/models and POST /v1/audio/transcriptions behind a bearer token, as at
OpenAI.

The request is a multipart form: file (required), model (taken and ignored: the service has one model), language,
prompt, response_format (json by default, text, verbose_json). Errors are JSON {"error": {"message", "type"}}:
400 — a bad form, 401 — no or a wrong token, 404 — another path, 413 — the body or the audio over the limit,
422 — not audio, 503 — the model is not ready or the queue is full, 504 — over WHISPER_TIMEOUT, 500 — without
details.
A body larger than the limit is refused before it is read.
"""

from __future__ import annotations

import email.parser
import email.policy
import hmac
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import Settings
from .transcriber import AudioError, NotReady, TimedOut

logger = logging.getLogger("mercurius_whisper")

MODULE = "whisper"
PATH = "/v1/audio/transcriptions"
# room for the form around the file: the boundaries and the small fields
_FORM_OVERHEAD = 64 * 1024
_FORMATS = ("json", "text", "verbose_json")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # many voice messages at once are queued by the transcriber, not by the backlog
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], settings: Settings, transcriber: Any) -> None:
        super().__init__(address, Handler)
        self.settings = settings
        self.transcriber = transcriber
        self.inflight = 0
        self._count = threading.Lock()

    def enter(self) -> bool:
        """Take a place: settings.concurrency at work and up to settings.queue waiting; False — the queue is full."""
        with self._count:
            if self.inflight >= self.settings.concurrency + self.settings.queue:
                return False
            self.inflight += 1
            return True

    def leave(self) -> None:
        with self._count:
            self.inflight -= 1


def make_server(settings: Settings, transcriber: Any, host: str = "0.0.0.0", port: int | None = None) -> Server:
    return Server((host, settings.port if port is None else port), settings, transcriber)


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"
    server_version = "mercurius-whisper"
    sys_version = ""
    # a slow client must not hold a thread forever
    timeout = 60

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — the name is the base class's
        pass  # the access log would carry nothing useful; results are logged in _transcribe

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/v1/models":
            if self._authorized():
                self._json(200, {"object": "list",
                                 "data": [{"id": self.server.settings.model, "object": "model", "owned_by": MODULE}]})
            return
        if path != "/health":
            self._error(404, "not found", "not_found")
            return
        transcriber = self.server.transcriber
        state = {"status": "ok" if transcriber.state == "ready" else transcriber.state, "module": MODULE,
                 "model": self.server.settings.model}
        if transcriber.state == "failed":
            state["error"] = transcriber.error
        self._json(200 if transcriber.state == "ready" else 503, state)

    def _authorized(self) -> bool:
        expected = ("Bearer " + self.server.settings.token).encode()
        given = (self.headers.get("Authorization") or "").strip().encode()
        if hmac.compare_digest(expected, given):
            return True
        self._error(401, "a valid bearer token is required", "authentication_error", close=True)
        return False

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != PATH:
            self._error(404, "not found", "not_found", close=True)
            return
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            length = -1
        if length < 0:
            self._error(411, "Content-Length is required", "invalid_request_error", close=True)
            return
        if length > self.server.settings.max_bytes + _FORM_OVERHEAD:
            self._error(413, f"the body is over {self.server.settings.max_bytes // (1024 * 1024)} MB",
                        "invalid_request_error", close=True)
            return
        ctype = self.headers.get("Content-Type") or ""
        if not ctype.lower().startswith("multipart/form-data"):
            self._error(400, "the body must be multipart/form-data", "invalid_request_error", close=True)
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._error(400, "the body is shorter than Content-Length", "invalid_request_error", close=True)
            return
        form = _parse_form(ctype, body)
        data = form.get("file")
        if not isinstance(data, bytes) or data == b"":
            self._error(400, "the form needs a non-empty file", "invalid_request_error")
            return
        if len(data) > self.server.settings.max_bytes:
            self._error(413, f"the file is over {self.server.settings.max_bytes // (1024 * 1024)} MB",
                        "invalid_request_error")
            return
        fmt = _text(form.get("response_format")) or "json"
        if fmt not in _FORMATS:
            self._error(400, "response_format must be json, text or verbose_json", "invalid_request_error")
            return
        if not self.server.enter():
            self._error(503, "busy: the queue of recognitions is full", "server_busy", retry=30)
            return
        try:
            self._transcribe(data, _text(form.get("language")), _text(form.get("prompt")), fmt)
        finally:
            self.server.leave()

    def _transcribe(self, data: bytes, language: str | None, prompt: str | None, fmt: str) -> None:
        started = time.monotonic()
        try:
            result = self.server.transcriber.transcribe(data, language, prompt)
        except NotReady as exc:
            self._error(503, f"the model is not ready ({exc})", "server_busy", retry=60)
            return
        except TimedOut as exc:
            self._error(504, str(exc), "timeout")
            return
        except AudioError as exc:
            self._error(422, f"not audio: {exc}", "invalid_request_error")
            return
        except Exception as exc:
            logger.error("transcription failed: %s", type(exc).__name__)
            self._error(500, "the transcription failed", "server_error")
            return
        logger.info("transcribed %.1f s of audio in %.1f s, language %s, %d characters",
                    result.seconds, time.monotonic() - started, result.language, len(result.text))
        if fmt == "text":
            self._send(200, "text/plain; charset=utf-8", result.text.encode())
        elif fmt == "verbose_json":
            self._json(200, {"text": result.text, "language": result.language, "duration": result.seconds})
        else:
            self._json(200, {"text": result.text})

    def _json(self, status: int, payload: dict[str, Any], close: bool = False, retry: int = 0) -> None:
        self._send(status, "application/json", json.dumps(payload, ensure_ascii=False).encode(), close, retry)

    def _error(self, status: int, message: str, kind: str, close: bool = False, retry: int = 0) -> None:
        self._json(status, {"error": {"message": message, "type": kind}}, close, retry)

    def _send(self, status: int, ctype: str, body: bytes, close: bool = False, retry: int = 0) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if retry:
            self.send_header("Retry-After", str(retry))
        if close:
            # the body of the request was not read: the connection cannot carry another request
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)


def _parse_form(ctype: str, body: bytes) -> dict[str, Any]:
    """The fields of a multipart form: the file as bytes, the others as text; a broken form gives what was read."""
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + ctype.encode("latin-1", "replace") + b"\r\n\r\n" + body)
    fields: dict[str, Any] = {}
    if not message.is_multipart():
        return fields
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or name in fields:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        fields[name] = payload if name == "file" else payload.decode("utf-8", "replace")
    return fields


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
