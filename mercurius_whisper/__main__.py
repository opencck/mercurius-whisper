"""Start: read the settings, load the model in the background (/health answers 503 until it is ready), serve.

Exit 78 — a bad setting (as the other modules of Mercurius). SIGTERM and SIGINT stop the server.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

from .config import ConfigError, Settings
from .server import make_server
from .transcriber import Transcriber


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    # the Hub client logs every request of a download with its address; one line of our own is enough
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("mercurius_whisper")
    try:
        settings = Settings.from_env(os.environ)
    except ConfigError as exc:
        log.error("%s", exc)
        return 78
    transcriber = Transcriber(settings)
    server = make_server(settings, transcriber)
    # the first start downloads the model, which takes minutes: the port is open at once, /health says "loading"
    threading.Thread(target=transcriber.load, name="load-model", daemon=True).start()

    def stop(signum: int, frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("listening on :%d, model %s on %s (%s), language %s, %d threads, %d at once", settings.port,
             settings.model, settings.device, settings.compute_type, settings.language or "auto", settings.threads,
             settings.concurrency)
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
