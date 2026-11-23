[English](README.md) | **Русский** | [中文](README.cn.md)

# mercurius-whisper

Небольшой HTTP-сервис, который распознаёт речь в текст с помощью
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) на самой машине, не отправляя звук наружу. Это
необязательный модуль [Меркурия](https://github.com/opencck/mercurius), но работает и сам по себе: он отвечает тем
же маршрутом распознавания речи, что и OpenAI API, поэтому его может вызывать любой клиент этого API.

**Состояние: в разработке.** В репозитории пока описание сервиса; код — следующими коммитами.

## API (план)

Все маршруты, кроме `/health`, требуют `Authorization: Bearer <WHISPER_TOKEN>`.

| Маршрут | Ответ |
|---|---|
| `GET /health` | `{"status":"ok","module":"whisper","model":"<загруженная модель>"}`, когда модель загружена |
| `POST /v1/audio/transcriptions` | форма multipart: `file` (звук), `model`, необязательные `language`, `prompt`, `response_format` (`json` или `text`). Ответ `{"text": "…"}` |
| `GET /v1/models` | модели, которые сервис может загрузить |

Ошибки — в форме OpenAI API: `401` без токена, `413` — файл больше предела, `422` — звук не читается, `503` — модель
ещё загружается.

## Настройки (план)

| Переменная | По умолчанию | Что значит |
|---|---|---|
| `WHISPER_TOKEN` | — | обязательна, 16+ символов |
| `WHISPER_MODEL` | `small` | модель faster-whisper: `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` на процессоре; `float16` на видеокарте |
| `WHISPER_DEVICE` | `cpu` | `cpu` или `cuda` |
| `WHISPER_MAX_MB` | `25` | наибольший файл |
| `WHISPER_TIMEOUT` | `300` | секунд на один файл |

Модель скачивается один раз в том и загружается при старте.

## С Меркурием

Модуль работает в профиле compose `whisper`. Агент вызывает его как свою модель речи:
`MEDIA_ENDPOINTS=whisper=http://whisper:8000/v1`, `MEDIA_SPEECH_MODELS=custom:whisper/small`, токен — секрет
хранилища `media-endpoint-whisper`.

## Лицензия

MIT
