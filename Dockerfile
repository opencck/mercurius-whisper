# Speech to text on this host: faster-whisper (CTranslate2) behind an OpenAI-compatible POST /v1/audio/transcriptions.
# One image for amd64 and arm64; the audio is decoded by PyAV in memory, no ffmpeg in the system. The model is
# downloaded once to /models.
# A module of the Mercurius agent: https://github.com/opencck/mercurius
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    HF_HOME=/models/hub \
    HF_HUB_DISABLE_TELEMETRY=1
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt \
    && useradd --system --uid 10060 --home /models whisper \
    && mkdir -p /models && chown whisper /models
COPY mercurius_whisper /app/mercurius_whisper
WORKDIR /app
USER whisper
EXPOSE 8000
VOLUME /models
# 503 until the model is loaded (the first start downloads it): the start period covers the download
HEALTHCHECK --interval=30s --timeout=5s --start-period=900s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"]
ENTRYPOINT ["python", "-m", "mercurius_whisper"]
