import threading
import time
from types import SimpleNamespace

import pytest

from mercurius_whisper.config import Settings
from mercurius_whisper.transcriber import AudioError, FifoGate, NotReady, TimedOut, Transcriber

TOKEN = "t" * 24


def seg(text, no_speech=0.1, logprob=-0.3):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


class FakeModel:
    supported_languages = ["ru", "en"]

    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return iter(self.segments), SimpleNamespace(language="ru", duration=len(audio) / 16000)


def settings(**extra):
    return Settings.from_env({"WHISPER_TOKEN": TOKEN, **extra})


def make(segments=None, s=None, decode=None, loader=None, clock=time.monotonic):
    model = FakeModel(segments if segments is not None else [seg(" Привет "), seg("мир")])
    t = Transcriber(
        s or settings(),
        load_model=loader or (lambda _: model),
        decode=decode or (lambda data: [0.0] * 16000 * 2),
        clock=clock,
    )
    return t, model


def test_not_ready_before_load():
    t, _ = make()
    assert t.state == "loading"
    with pytest.raises(NotReady):
        t.transcribe(b"x")


def test_joins_segments_with_the_settings_against_hallucinations():
    t, model = make()
    t.load()
    assert t.state == "ready"
    result = t.transcribe(b"audio")
    assert (result.text, result.language, result.seconds) == ("Привет мир", "ru", 2.0)
    kwargs = model.calls[0]
    assert kwargs["beam_size"] == 5
    assert kwargs["condition_on_previous_text"] is False
    assert kwargs["vad_filter"] is True
    assert kwargs["vad_parameters"] == {"min_silence_duration_ms": 500}
    assert kwargs["no_speech_threshold"] == 0.6
    assert kwargs["log_prob_threshold"] == -1.0
    assert "language" not in kwargs


def test_drops_silence_hallucinations_only_when_both_signs():
    t, _ = make([seg("Продолжение следует...", no_speech=0.9, logprob=-1.5),
                 seg("тихо, но речь", no_speech=0.9, logprob=-0.2),
                 seg("уверенно", no_speech=0.1, logprob=-1.5)])
    t.load()
    assert t.transcribe(b"a").text == "тихо, но речь уверенно"


def test_language_from_request_then_settings():
    t, model = make(s=settings(WHISPER_LANGUAGE="en"))
    t.load()
    for language in (None, "ru-RU", "xx", "auto"):
        t.transcribe(b"a", language=language)
    assert [c.get("language") for c in model.calls] == ["en", "ru", "en", None]


def test_prompt_goes_to_initial_prompt():
    t, model = make()
    t.load()
    t.transcribe(b"a", prompt="Меркурий")
    assert model.calls[0]["initial_prompt"] == "Меркурий"


def test_a_long_recognition_is_cut_by_the_timeout():
    now = [0.0]

    def clock():
        now[0] += 40.0  # every look at the clock: 40 s later
        return now[0]

    t, _ = make([seg("раз"), seg("два"), seg("три"), seg("четыре"), seg("пять"), seg("шесть"), seg("семь"),
                 seg("восемь"), seg("девять")], s=settings(WHISPER_TIMEOUT="100"), clock=clock)
    t.load()
    with pytest.raises(TimedOut):
        t.transcribe(b"a")


def test_unreadable_audio():
    def bad(data):
        raise ValueError("Invalid data found when processing input")

    t, _ = make(decode=bad)
    t.load()
    with pytest.raises(AudioError, match="Invalid data"):
        t.transcribe(b"a")


def test_a_fault_of_the_program_is_not_called_bad_audio():
    def broken(data):
        raise TypeError("open() got an unexpected keyword argument")

    t, _ = make(decode=broken)
    t.load()
    with pytest.raises(TypeError):
        t.transcribe(b"a")


def test_failed_load_is_reported():
    def broken(_):
        raise RuntimeError("no network")

    t, _ = make(loader=broken)
    t.load()
    assert (t.state, t.error) == ("failed", "RuntimeError")
    with pytest.raises(NotReady):
        t.transcribe(b"a")


def test_no_more_recognitions_at_once_than_the_setting():
    inside = 0
    peak = 0
    lock = threading.Lock()

    class Slow(FakeModel):
        def transcribe(self, audio, **kwargs):
            nonlocal inside, peak
            with lock:
                inside += 1
                peak = max(peak, inside)
            time.sleep(0.05)
            with lock:
                inside -= 1
            return iter([seg("x")]), SimpleNamespace(language="ru", duration=1.0)

    for concurrency in (1, 2):
        peak = 0
        slow = Slow([])
        t = Transcriber(settings(WHISPER_CONCURRENCY=str(concurrency)), load_model=lambda _, m=slow: m,
                        decode=lambda d: [0.0] * 16000)
        t.load()
        threads = [threading.Thread(target=t.transcribe, args=(b"a",)) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert peak == concurrency


def test_the_gate_lets_in_by_the_order_of_coming():
    gate = FifoGate(1)
    order = []
    gate.enter()
    threads = []
    for i in range(4):
        th = threading.Thread(target=lambda i=i: (gate.enter(), order.append(i), gate.leave()))
        th.start()
        threads.append(th)
        for _ in range(100):  # wait until it stands in the line
            if gate.waiting == i + 1:
                break
            time.sleep(0.01)
    gate.leave()
    for th in threads:
        th.join()
    assert order == [0, 1, 2, 3]
