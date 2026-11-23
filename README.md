**English** | [Русский](README.ru.md) | [中文](README.cn.md)

# mercurius-whisper

A small HTTP service that turns speech into text with [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
on the machine itself, without sending the audio anywhere. It is an optional module of
[Mercurius](https://github.com/opencck/mercurius) and can be used on its own: it answers the speech-to-text route of
the OpenAI API, so any client of that API can call it.

## API

Every route except `/health` needs `Authorization: Bearer <WHISPER_TOKEN>`.

| Route | Answer |
|---|---|
| `GET /health` | `200` `{"status":"ok","module":"whisper","model":"small"}` once the model is loaded; `503` with `"status":"loading"` while it loads, `"failed"` when it did not load |
| `POST /v1/audio/transcriptions` | multipart form: `file` (audio), `model` (accepted, not used), optional `language`, `prompt`, `response_format` (`json` — default, `text`, `verbose_json`). Answer `{"text": "…"}` |
| `GET /v1/models` | the loaded model |

Voice messages of Telegram (OGG/Opus), MP3, M4A, WAV and other formats are decoded in memory by PyAV, which comes
with faster-whisper; no ffmpeg in the system is needed.

Errors are in the form of the OpenAI API: `401` without the token, `413` for a file over the limit, `422` when the
audio cannot be read, `503` while the model is loading or when the queue is full, `504` when the recognition runs
over the timeout.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `WHISPER_TOKEN` | — | required, 16+ characters (`openssl rand -hex 24`) |
| `WHISPER_MODEL` | `small` | a faster-whisper size (`tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`) or a Hugging Face repository |
| `WHISPER_DEVICE` | `cpu` | `cpu`, `cuda` or `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` on a CPU; `float16` on a GPU |
| `WHISPER_LANGUAGE` | `auto` | the default language (`ru`, `en`…); the request's `language` wins |
| `WHISPER_THREADS` | `4` | CPU threads of the model |
| `WHISPER_MAX_MB` | `25` | the largest file |
| `WHISPER_TIMEOUT` | `300` | seconds for one file |
| `WHISPER_CONCURRENCY` | `1` | files recognized at once; the others wait in the order they came |
| `WHISPER_QUEUE` | `8` | requests waiting beyond them; the next one gets `503` |
| `WHISPER_PORT` | `8000` | the port |

The model is downloaded once into the volume `/models` and loaded at start; after that no network is needed. On four
CPU threads `small` recognizes a voice message of 3.5 s in about 6 s and takes about 0.8 GB of memory; `turbo` is more
accurate and takes about 1.7 GB.

## Run

```sh
docker build -t mercurius-whisper .
export WHISPER_TOKEN=$(openssl rand -hex 24)
docker run --rm -e WHISPER_TOKEN -v $PWD/models:/models -p 8000:8000 mercurius-whisper
curl -H "Authorization: Bearer $WHISPER_TOKEN" -F file=@voice.oga http://127.0.0.1:8000/v1/audio/transcriptions
```

Checks: `ruff check .`, `mypy`, `python -m pytest -q`.

## Use with Mercurius

The module runs in the compose profile `whisper`. The agent calls it as a model of its own for speech:
`MEDIA_ENDPOINTS=whisper=http://whisper:8000/v1`, `MEDIA_SPEECH_MODELS=custom:whisper/small`, the token — the vault
secret `media-endpoint-whisper`.

## License

MIT. faster-whisper: MIT; Whisper models: MIT.
