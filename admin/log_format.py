"""JSON log lines for PROD, the same fields the services' logging_conf.py writes."""

import json
import logging


class JsonFormatter(logging.Formatter):
    """Renders each record as one JSON object: timestamp, level, logger, message, exc_info."""

    def format(self, record: logging.LogRecord) -> str:
        """The record as a single-line JSON string."""
        line = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            line["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(line)
