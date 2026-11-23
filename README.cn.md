[English](README.md) | [Русский](README.ru.md) | **中文**

# mercurius-whisper

一个小型 HTTP 服务，使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 在本机把语音转成文字，音频不会发往任何地方。它是
[Mercurius](https://github.com/opencck/mercurius) 的可选模块，也可以单独使用：它提供与 OpenAI API 相同的语音转文字路由，因此该 API 的任何客户端都能调用它。

**状态：开发中。** 仓库目前只有服务说明；代码随后提交。

## API（计划）

除 `/health` 外，所有路由都需要 `Authorization: Bearer <WHISPER_TOKEN>`。

| 路由 | 响应 |
|---|---|
| `GET /health` | 模型加载完成后返回 `{"status":"ok","module":"whisper","model":"<已加载的模型>"}` |
| `POST /v1/audio/transcriptions` | multipart 表单：`file`（音频）、`model`，可选 `language`、`prompt`、`response_format`（`json` 或 `text`）。响应 `{"text": "…"}` |
| `GET /v1/models` | 服务可以加载的模型 |

错误采用 OpenAI API 的格式：缺少令牌 `401`，文件超过上限 `413`，音频无法读取 `422`，模型仍在加载 `503`。

## 设置（计划）

| 变量 | 默认值 | 含义 |
|---|---|---|
| `WHISPER_TOKEN` | — | 必填，16 个字符以上 |
| `WHISPER_MODEL` | `small` | faster-whisper 模型：`tiny`、`base`、`small`、`medium`、`large-v3`、`turbo` |
| `WHISPER_COMPUTE_TYPE` | `int8` | CPU 上用 `int8`；GPU 上用 `float16` |
| `WHISPER_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `WHISPER_MAX_MB` | `25` | 文件上限 |
| `WHISPER_TIMEOUT` | `300` | 单个文件的秒数 |

模型只下载一次到数据卷，并在启动时加载。

## 与 Mercurius 一起使用

模块运行在 compose 配置 `whisper` 中。代理把它当作自己的语音模型调用：
`MEDIA_ENDPOINTS=whisper=http://whisper:8000/v1`，`MEDIA_SPEECH_MODELS=custom:whisper/small`，令牌是保管库中的密钥
`media-endpoint-whisper`。

## 许可证

MIT
