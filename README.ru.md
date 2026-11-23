[English](README.md) | **Русский** | [中文](README.cn.md)

# mercurius-whisper

Небольшой HTTP-сервис, который распознаёт речь в текст с помощью
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) на самой машине, не отправляя звук наружу. Это
необязательный модуль [Меркурия](https://github.com/opencck/mercurius), но работает и сам по себе: он отвечает тем
же маршрутом распознавания речи, что и OpenAI API, поэтому его может вызывать любой клиент этого API.

## API

Все маршруты, кроме `/health`, требуют `Authorization: Bearer <WHISPER_TOKEN>`.

| Маршрут | Ответ |
|---|---|
| `GET /health` | `200` `{"status":"ok","module":"whisper","model":"small"}`, когда модель загружена; `503` и `"status":"loading"`, пока грузится, `"failed"` — не загрузилась |
| `POST /v1/audio/transcriptions` | форма multipart: `file` (звук), `model` (принимается, не учитывается), необязательные `language`, `prompt`, `response_format` (`json` — по умолчанию, `text`, `verbose_json`). Ответ `{"text": "…"}` |
| `GET /v1/models` | загруженная модель |

Голосовые Telegram (OGG/Opus), MP3, M4A, WAV и другие форматы декодируются в памяти библиотекой PyAV, которая идёт с
faster-whisper; ffmpeg в системе не нужен.

Ошибки — в форме OpenAI API: `401` без токена, `413` — файл больше предела, `422` — звук не читается, `503` — модель
ещё загружается или очередь полна, `504` — распознавание дольше предела времени.

## Настройки

| Переменная | По умолчанию | Что значит |
|---|---|---|
| `WHISPER_TOKEN` | — | обязательна, 16+ символов (`openssl rand -hex 24`) |
| `WHISPER_MODEL` | `small` | размер faster-whisper (`tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`) или репозиторий Hugging Face |
| `WHISPER_DEVICE` | `cpu` | `cpu`, `cuda` или `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` на процессоре; `float16` на видеокарте |
| `WHISPER_LANGUAGE` | `auto` | язык по умолчанию (`ru`, `en`…); `language` запроса важнее |
| `WHISPER_THREADS` | `4` | потоков процессора у модели |
| `WHISPER_MAX_MB` | `25` | наибольший файл |
| `WHISPER_TIMEOUT` | `300` | секунд на один файл |
| `WHISPER_CONCURRENCY` | `1` | файлов распознаётся одновременно; остальные ждут по порядку прихода |
| `WHISPER_QUEUE` | `8` | сколько запросов ждёт сверх них; следующий получает `503` |
| `WHISPER_PORT` | `8000` | порт |

Модель скачивается один раз в том `/models` и загружается при старте; дальше сеть не нужна. На четырёх потоках
процессора `small` распознаёт голосовое в 3,5 с примерно за 6 с и занимает около 0,8 ГБ памяти; `turbo` точнее и
занимает около 1,7 ГБ.

## Запуск

```sh
docker build -t mercurius-whisper .
export WHISPER_TOKEN=$(openssl rand -hex 24)
docker run --rm -e WHISPER_TOKEN -v $PWD/models:/models -p 8000:8000 mercurius-whisper
curl -H "Authorization: Bearer $WHISPER_TOKEN" -F file=@voice.oga http://127.0.0.1:8000/v1/audio/transcriptions
```

Проверки: `ruff check .`, `mypy`, `python -m pytest -q`.

## С Меркурием

Модуль работает в профиле compose `whisper`. Агент вызывает его как свою модель речи:
`MEDIA_ENDPOINTS=whisper=http://whisper:8000/v1`, `MEDIA_SPEECH_MODELS=custom:whisper/small`, токен — секрет
хранилища `media-endpoint-whisper`.

## Лицензия

MIT. faster-whisper — MIT; модели Whisper — MIT.
