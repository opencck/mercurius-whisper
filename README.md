**English** | [Русский](README.ru.md) | [中文](README.cn.md)

# mercurius-whisper

A small HTTP service that turns speech into text with [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
on the machine itself, without sending the audio anywhere. It is an optional module of
[Mercurius](https://github.com/opencck/mercurius) and can be used on its own: it answers the speech-to-text route of
the OpenAI API, so any client of that API can call it.

**Status: in development.** The repository holds the description of the service; the code comes next.

## API (planned)

Every route except `/health` needs `Authorization: Bearer <WHISPER_TOKEN>`.

| Route | Answer |
|---|---|
| `GET /health` | `{"status":"ok","module":"whisper","model":"<loaded model>"}` once the model is loaded |
| `POST /v1/audio/transcriptions` | multipart form: `file` (audio), `model`, optional `language`, `prompt`, `response_format` (`json` or `text`). Answer `{"text": "…"}` |
| `GET /v1/models` | the models the service can load |

Errors are in the form of the OpenAI API: `401` without the token, `413` for a file over the limit, `422` when the
audio cannot be read, `503` while the model is loading.

## Settings (planned)

| Variable | Default | Meaning |
|---|---|---|
| `WHISPER_TOKEN` | — | required, 16+ characters |
| `WHISPER_MODEL` | `small` | the faster-whisper model: `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` on a CPU; `float16` on a GPU |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_MAX_MB` | `25` | the largest file |
| `WHISPER_TIMEOUT` | `300` | seconds for one file |

The model is downloaded once into a volume and loaded at start.

## Use with Mercurius

The module runs in the compose profile `whisper`. The agent calls it as a model of its own for speech:
`MEDIA_ENDPOINTS=whisper=http://whisper:8000/v1`, `MEDIA_SPEECH_MODELS=custom:whisper/small`, the token — the vault
secret `media-endpoint-whisper`.

## License

MIT
