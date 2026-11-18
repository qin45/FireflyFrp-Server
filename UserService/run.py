from __future__ import annotations

import uvicorn

from app.config import load_settings
from app.factory import create_app


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
