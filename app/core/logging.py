"""
Structured logging configuration.

Why not just `print()` or the default root logger:
- Production log aggregators (CloudWatch, Datadog, ELK) need consistent,
  parseable log lines with timestamps and levels
- A named logger per module lets us trace which layer produced a log line
  (app.services.auth vs app.repositories.user), critical when debugging
  a production incident under time pressure
"""

import logging
import sys

from app.core.config import settings


def configure_logging() -> None:
    """Configure the root logger once, at application startup."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger. Use as: logger = get_logger(__name__)."""
    return logging.getLogger(name)
