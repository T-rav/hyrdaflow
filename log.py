"""Structured JSON logging for HydraFlow."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        # Merge extra fields injected by adapters
        for key in ("issue", "worker", "pr", "phase", "batch"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, default=str)


def setup_logging(
    *,
    level: int = logging.INFO,
    json_output: bool = True,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """Configure the ``hydraflow`` logger.

    Parameters
    ----------
    level:
        Logging level.
    json_output:
        If *True*, use JSON formatting; otherwise plain text.
    log_file:
        Optional path to a log file.  When provided a
        :class:`~logging.handlers.RotatingFileHandler` is added
        alongside the console handler (10 MB max, 5 backups,
        always JSON-formatted for Loki/Grafana ingestion).

    Returns
    -------
    logging.Logger
        The configured root ``hydraflow`` logger.
    """
    logger = logging.getLogger("hydraflow")
    logger.setLevel(level)
    logger.handlers.clear()

    formatter: logging.Formatter
    if json_output:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (always JSON for machine ingestion)
    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)

    return logger
