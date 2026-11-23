"""Settings from the environment, checked once at start: a bad value stops the service, the message names the variable
and never its value."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

# A model is a faster-whisper size (tiny, base, small, medium, large-v3, turbo…) or a Hugging Face repository
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_DEVICES = ("cpu", "cuda", "auto")
# the compute types of CTranslate2
_COMPUTE_TYPES = ("int8", "int8_float32", "int8_float16", "int8_bfloat16", "int16", "float16", "bfloat16", "float32",
                  "auto", "default")


class ConfigError(ValueError):
    """A setting is missing or out of range."""


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number from {low} to {high}") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be a whole number from {low} to {high}")
    return value


def _choice(env: Mapping[str, str], name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = env.get(name, "").strip().lower() or default
    if value not in allowed:
        raise ConfigError(f"{name} must be one of: {', '.join(allowed)}")
    return value


def normalize_language(value: str | None) -> str | None:
    """A Whisper language code (ru, en, haw…) from ru, RU, ru-RU or ru_RU; None for auto, empty or not a code."""
    if value is None:
        return None
    raw = value.strip().lower().replace("_", "-").split("-", 1)[0]
    if raw in ("", "auto"):
        return None
    return raw if _LANGUAGE.match(raw) else None


@dataclass(frozen=True)
class Settings:
    token: str
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    threads: int = 4
    max_bytes: int = 25 * 1024 * 1024
    timeout: int = 300
    concurrency: int = 1
    queue: int = 8
    port: int = 8000
    models_dir: str = "/models"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        token = env.get("WHISPER_TOKEN", "").strip()
        if len(token) < 16:
            raise ConfigError("WHISPER_TOKEN must be at least 16 characters (openssl rand -hex 24)")
        model = env.get("WHISPER_MODEL", "").strip() or cls.model
        if not _MODEL.match(model) or ".." in model:
            raise ConfigError("WHISPER_MODEL must be a faster-whisper size or a repository author/name")
        raw_language = env.get("WHISPER_LANGUAGE", "").strip()
        language = normalize_language(raw_language)
        if language is None and raw_language.lower() not in ("", "auto"):
            raise ConfigError("WHISPER_LANGUAGE must be auto or a language code (ru, en…)")
        return cls(
            token=token,
            model=model,
            device=_choice(env, "WHISPER_DEVICE", cls.device, _DEVICES),
            compute_type=_choice(env, "WHISPER_COMPUTE_TYPE", cls.compute_type, _COMPUTE_TYPES),
            language=language,
            threads=_int(env, "WHISPER_THREADS", cls.threads, 1, 64),
            max_bytes=_int(env, "WHISPER_MAX_MB", 25, 1, 500) * 1024 * 1024,
            timeout=_int(env, "WHISPER_TIMEOUT", cls.timeout, 10, 3600),
            concurrency=_int(env, "WHISPER_CONCURRENCY", cls.concurrency, 1, 16),
            queue=_int(env, "WHISPER_QUEUE", cls.queue, 0, 256),
            port=_int(env, "WHISPER_PORT", cls.port, 1, 65535),
            models_dir=env.get("WHISPER_MODELS_DIR", "").strip() or cls.models_dir,
        )
