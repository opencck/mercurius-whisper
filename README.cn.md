[English](README.md) | [Русский](README.ru.md) | **中文**

# mercurius-whisper

一个小型 HTTP 服务，使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 在本机把语音转成文字，音频不会发往任何地方。它是
[Mercurius](https://github.com/opencck/mercurius) 的可选模块，也可以单独使用：它提供与 OpenAI API 相同的语音转文字路由，因此该 API 的任何客户端都能调用它。

## API

除 `/health` 外，所有路由都需要 `Authorization: Bearer <WHISPER_TOKEN>`。

| 路由 | 响应 |
|---|---|
| `GET /health` | 模型加载完成后返回 `200` `{"status":"ok","module":"whisper","model":"small"}`；加载中返回 `503` 和 `"status":"loading"`，加载失败为 `"failed"` |
| `POST /v1/audio/transcriptions` | multipart 表单：`file`（音频）、`model`（接受但不使用），可选 `language`、`prompt`、`response_format`（`json` 为默认，`text`、`verbose_json`）。响应 `{"text": "…"}` |
| `GET /v1/models` | 已加载的模型 |

Telegram 语音消息（OGG/Opus）、MP3、M4A、WAV 等格式由 faster-whisper 自带的 PyAV 在内存中解码，系统中不需要 ffmpeg。

错误采用 OpenAI API 的格式：缺少令牌 `401`，文件超过上限 `413`，音频无法读取 `422`，模型仍在加载或队列已满 `503`，识别超时 `504`。

## 设置

| 变量 | 默认值 | 含义 |
|---|---|---|
| `WHISPER_TOKEN` | — | 必填，16 个字符以上（`openssl rand -hex 24`） |
| `WHISPER_MODEL` | `small` | faster-whisper 尺寸（`tiny`、`base`、`small`、`medium`、`large-v3`、`turbo`）或 Hugging Face 仓库 |
| `WHISPER_DEVICE` | `cpu` | `cpu`、`cuda` 或 `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` | CPU 上用 `int8`；GPU 上用 `float16` |
| `WHISPER_LANGUAGE` | `auto` | 默认语言（`ru`、`en`…）；请求中的 `language` 优先 |
| `WHISPER_THREADS` | `4` | 模型使用的 CPU 线程数 |
| `WHISPER_MAX_MB` | `25` | 文件上限 |
| `WHISPER_TIMEOUT` | `300` | 单个文件的秒数 |
| `WHISPER_CONCURRENCY` | `1` | 同时识别的文件数；其余按到达顺序等待 |
| `WHISPER_QUEUE` | `8` | 超出后可等待的请求数；再来的请求得到 `503` |
| `WHISPER_PORT` | `8000` | 端口 |

模型只下载一次到数据卷 `/models`，并在启动时加载；之后不再需要网络。在 4 个 CPU 线程上，`small` 识别一条 3.5 秒的语音约需 6 秒，占用约 0.8 GB 内存；`turbo` 更准确，占用约 1.7 GB。

## 运行

```sh
docker build -t mercurius-whisper .
export WHISPER_TOKEN=$(openssl rand -hex 24)
docker run --rm -e WHISPER_TOKEN -v $PWD/models:/models -p 8000:8000 mercurius-whisper
curl -H "Authorization: Bearer $WHISPER_TOKEN" -F file=@voice.oga http://127.0.0.1:8000/v1/audio/transcriptions
```

检查：`ruff check .`、`mypy`、`python -m pytest -q`。

## 与 Mercurius 一起使用

模块运行在 compose 配置 `whisper` 中。代理把它当作自己的语音模型调用：
`MEDIA_ENDPOINTS=whisper=http://whisper:8000/v1`，`MEDIA_SPEECH_MODELS=custom:whisper/small`，令牌是保管库中的密钥
`media-endpoint-whisper`。

## 许可证

MIT。faster-whisper：MIT；Whisper 模型：MIT。
