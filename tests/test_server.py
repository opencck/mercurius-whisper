import http.client
import json
import threading
import uuid

import pytest

from mercurius_whisper.config import Settings
from mercurius_whisper.server import make_server
from mercurius_whisper.transcriber import AudioError, NotReady, Result, TimedOut

TOKEN = "t" * 24


class FakeTranscriber:
    def __init__(self):
        self.state = "ready"
        self.error = None
        self.calls = []
        self.raise_ = None
        self.release = None

    def transcribe(self, data, language=None, prompt=None):
        if self.release is not None:
            self.release.wait(5)
        self.calls.append((data, language, prompt))
        if self.raise_ is not None:
            raise self.raise_
        return Result("Привет", "ru", 1.5)


@pytest.fixture
def env():
    settings = Settings.from_env(
        {"WHISPER_TOKEN": TOKEN, "WHISPER_MAX_MB": "1", "WHISPER_QUEUE": "1"})
    fake = FakeTranscriber()
    server = make_server(settings, fake, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.fake = fake
    yield server.server_address[1], fake, server
    server.shutdown()
    server.server_close()


def multipart(fields, file=b"OggS-voice", filename="voice.oga"):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    if file is not None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode() + file + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, response.getheader("Content-Type", ""), data


def post(port, fields=None, file=b"OggS-voice", token=TOKEN, extra=None):
    body, ctype = multipart(fields or {"model": "whisper"}, file)
    headers = {"Content-Type": ctype}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra or {})
    return request(port, "POST", "/v1/audio/transcriptions", body, headers)


def test_health_is_open(env):
    port, fake, _ = env
    status, _, data = request(port, "GET", "/health")
    assert status == 200
    assert json.loads(data) == {"status": "ok", "module": "whisper", "model": "small"}


def test_health_while_loading_and_failed(env):
    port, fake, _ = env
    fake.state = "loading"
    status, _, data = request(port, "GET", "/health")
    assert (status, json.loads(data)["status"]) == (503, "loading")
    fake.state, fake.error = "failed", "RuntimeError"
    status, _, data = request(port, "GET", "/health")
    assert status == 503
    assert json.loads(data) == {"status": "failed", "module": "whisper", "model": "small", "error": "RuntimeError"}


def test_transcribes(env):
    port, fake, _ = env
    status, ctype, data = post(port, {"model": "whisper", "language": "ru", "prompt": "Меркурий"})
    assert status == 200
    assert ctype.startswith("application/json")
    assert json.loads(data) == {"text": "Привет"}
    assert fake.calls == [(b"OggS-voice", "ru", "Меркурий")]


def test_text_and_verbose_formats(env):
    port, _, _ = env
    status, ctype, data = post(port, {"response_format": "text"})
    assert (status, data.decode()) == (200, "Привет")
    assert ctype.startswith("text/plain")
    status, _, data = post(port, {"response_format": "verbose_json"})
    assert json.loads(data) == {"text": "Привет", "language": "ru", "duration": 1.5}
    status, _, _ = post(port, {"response_format": "srt"})
    assert status == 400


@pytest.mark.parametrize("token", [None, "wrong-token-wrong-token", TOKEN + "x"])
def test_token_is_required(env, token):
    port, fake, _ = env
    status, _, _ = post(port, token=token)
    assert status == 401
    assert fake.calls == []


def test_missing_file(env):
    port, _, _ = env
    status, _, data = post(port, file=None)
    assert status == 400
    assert "file" in json.loads(data)["error"]["message"]


def test_empty_file(env):
    port, _, _ = env
    status, _, _ = post(port, file=b"")
    assert status == 400


def test_not_multipart(env):
    port, _, _ = env
    status, _, _ = request(port, "POST", "/v1/audio/transcriptions", b"raw",
                           {"Authorization": f"Bearer {TOKEN}", "Content-Type": "audio/ogg"})
    assert status == 400


def test_body_over_limit_is_refused_before_reading(env):
    port, fake, _ = env
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/v1/audio/transcriptions")
    conn.putheader("Authorization", f"Bearer {TOKEN}")
    conn.putheader("Content-Type", "multipart/form-data; boundary=x")
    conn.putheader("Content-Length", str(5 * 1024 * 1024))
    conn.endheaders()
    response = conn.getresponse()
    assert response.status == 413
    conn.close()
    assert fake.calls == []


def test_errors_of_the_transcriber(env):
    port, fake, _ = env
    fake.raise_ = AudioError("Invalid data found when processing input")
    status, _, data = post(port)
    assert status == 422
    assert "Invalid data" in json.loads(data)["error"]["message"]
    fake.raise_ = TimedOut(300)
    assert post(port)[0] == 504
    fake.raise_ = NotReady("loading")
    assert post(port)[0] == 503
    fake.raise_ = RuntimeError("secret detail")
    status, _, data = post(port)
    assert status == 500
    assert "secret" not in data.decode()


def test_models(env):
    port, _, _ = env
    status, _, data = request(port, "GET", "/v1/models", headers={"Authorization": f"Bearer {TOKEN}"})
    assert status == 200
    assert json.loads(data) == {"object": "list", "data": [{"id": "small", "object": "model", "owned_by": "whisper"}]}
    assert request(port, "GET", "/v1/models")[0] == 401


def test_unknown_path(env):
    port, _, _ = env
    assert request(port, "GET", "/nope")[0] == 404
    assert request(port, "POST", "/nope", b"", {"Authorization": f"Bearer {TOKEN}"})[0] == 404


def test_queue_is_limited(env):
    port, fake, server = env
    fake.release = threading.Event()
    results = []

    def call():
        results.append(post(port)[0])

    # queue 1: one at work and one waiting; the third is refused at once
    workers = [threading.Thread(target=call) for _ in range(2)]
    for worker in workers:
        worker.start()
    for _ in range(250):
        if server.inflight >= 2:
            break
        threading.Event().wait(0.02)
    status, _, _ = post(port)
    fake.release.set()
    for worker in workers:
        worker.join()
    assert status == 503
    assert sorted(results) == [200, 200]
