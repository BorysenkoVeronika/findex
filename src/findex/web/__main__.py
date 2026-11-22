"""Start the ASGI application with ``python -m findex.web``."""

import uvicorn

from findex.web.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run("findex.web.app:app", host="0.0.0.0", port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
