"""Structured logging via loguru, with stdlib logging routed through it.

The backend standard forbids ``print``. Every module logs through loguru; third-party
libraries that use the stdlib ``logging`` module are intercepted so their records land
in the same structured sink.
"""

import logging
import sys

from loguru import logger

from app.config import get_settings


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging() -> None:
    """Install the loguru sink and intercept stdlib logging once at startup."""
    settings = get_settings()
    logger.remove()
    # JSON in prod for machine ingestion; human-readable elsewhere.
    logger.add(
        sys.stdout,
        level="INFO",
        serialize=settings.is_prod,
        backtrace=False,
        diagnose=not settings.is_prod,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.INFO, force=True)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(name).handlers = [_InterceptHandler()]
        logging.getLogger(name).propagate = False
