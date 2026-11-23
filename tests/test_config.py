import pytest

from mercurius_whisper.config import ConfigError, Settings

TOKEN = "t" * 24


def test_defaults():
    s = Settings.from_env({"WHISPER_TOKEN": TOKEN})
    assert s.token == TOKEN
    assert s.model == "small"
    assert s.device == "cpu"
    assert s.compute_type == "int8"
    assert s.language is None
    assert s.threads == 4
    assert s.max_bytes == 25 * 1024 * 1024
    assert s.timeout == 300
    assert s.concurrency == 1
    assert s.queue == 8
    assert s.port == 8000
    assert s.models_dir == "/models"


def test_values():
    s = Settings.from_env({
        "WHISPER_TOKEN": TOKEN,
        "WHISPER_MODEL": "turbo",
        "WHISPER_DEVICE": "cuda",
        "WHISPER_COMPUTE_TYPE": "float16",
        "WHISPER_LANGUAGE": "RU",
        "WHISPER_THREADS": "2",
        "WHISPER_MAX_MB": "10",
        "WHISPER_TIMEOUT": "60",
        "WHISPER_CONCURRENCY": "2",
        "WHISPER_QUEUE": "0",
    })
    assert (s.model, s.device, s.compute_type, s.language, s.threads) == ("turbo", "cuda", "float16", "ru", 2)
    assert (s.max_bytes, s.timeout, s.concurrency, s.queue) == (10 * 1024 * 1024, 60, 2, 0)


def test_a_repository_is_a_model():
    assert Settings.from_env({"WHISPER_TOKEN": TOKEN, "WHISPER_MODEL": "Systran/faster-whisper-small"}).model \
        == "Systran/faster-whisper-small"


def test_short_token_is_refused():
    with pytest.raises(ConfigError, match="WHISPER_TOKEN"):
        Settings.from_env({"WHISPER_TOKEN": "short"})


def test_missing_token_is_refused():
    with pytest.raises(ConfigError, match="WHISPER_TOKEN"):
        Settings.from_env({})


@pytest.mark.parametrize("name,value", [
    ("WHISPER_THREADS", "0"),
    ("WHISPER_THREADS", "x"),
    ("WHISPER_MAX_MB", "501"),
    ("WHISPER_TIMEOUT", "5"),
    ("WHISPER_CONCURRENCY", "0"),
    ("WHISPER_QUEUE", "-1"),
    ("WHISPER_LANGUAGE", "russian"),
    ("WHISPER_MODEL", "../etc"),
    ("WHISPER_DEVICE", "tpu"),
    ("WHISPER_COMPUTE_TYPE", "int3"),
])
def test_bad_values_are_refused(name, value):
    with pytest.raises(ConfigError, match=name):
        Settings.from_env({"WHISPER_TOKEN": TOKEN, name: value})


def test_the_message_does_not_carry_the_value():
    with pytest.raises(ConfigError) as caught:
        Settings.from_env({"WHISPER_TOKEN": "secret-short"})
    assert "secret" not in str(caught.value)
