from __future__ import annotations

import uvicorn

from app.config import load_settings
from app.factory import create_app
from app.tls import ensure_tls_files


def main() -> None:
    settings = load_settings()
    app = create_app(settings)

    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None
    if settings.server.enable_https:
        cert_path, key_path = ensure_tls_files(settings.server)
        ssl_certfile = str(cert_path)
        ssl_keyfile = str(key_path)

    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        workers=1,
        log_level="info",
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


if __name__ == "__main__":
    main()
