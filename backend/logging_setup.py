import logging
import os
from logging.handlers import RotatingFileHandler

from backend.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = settings.log_dir
    os.makedirs(log_dir, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = [file_handler, console_handler]
    logging.getLogger("uvicorn.access").disabled = True

    logging.getLogger("__main__").info("Logging initialized: level=%s dir=%s", settings.log_level, log_dir)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
