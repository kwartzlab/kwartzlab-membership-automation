import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE")
    log_retention_days = int(os.getenv("LOG_RETENTION_DAYS", "7"))
    log_file_level = os.getenv("LOG_FILE_LEVEL", "DEBUG").upper()

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=log_retention_days,
            utc=True,
        )
        file_handler.setLevel(getattr(logging, log_file_level, logging.DEBUG))
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


    logging.getLogger("slack_sdk").setLevel(logging.INFO)
