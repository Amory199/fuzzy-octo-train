"""Structured JSON logging for FlowMesh.

Provides structured logging with context tracking for workflows and tasks.

Usage:
    from flowmesh.observability.logging import configure_logging, get_logger

    # Configure at application startup
    configure_logging(log_level="INFO", json_format=True)

    # Use in your code
    logger = get_logger(__name__)
    logger.info("Processing workflow", extra={"workflow_id": "abc123"})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Outputs log records as JSON with timestamp, level, message, and context.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields
        if hasattr(record, "workflow_id"):
            log_data["workflow_id"] = record.workflow_id

        if hasattr(record, "task_name"):
            log_data["task_name"] = record.task_name

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any additional fields from extra={}
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "workflow_id",
                "task_name",
            ]:
                log_data[key] = value

        return json.dumps(log_data)


class ContextFilter(logging.Filter):
    """Add contextual information to log records."""

    def __init__(self) -> None:
        super().__init__()
        self._context: dict[str, Any] = {}

    def set_context(self, **kwargs: Any) -> None:
        """Set context fields that will be added to all log records."""
        self._context.update(kwargs)

    def clear_context(self) -> None:
        """Clear all context fields."""
        self._context.clear()

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context to log record."""
        for key, value in self._context.items():
            setattr(record, key, value)
        return True


def configure_logging(
    log_level: str = "INFO",
    json_format: bool = True,
    include_stdlib: bool = False,
) -> None:
    """Configure application-wide logging.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Use JSON formatter if True, plain text if False
        include_stdlib: Include logs from standard library and dependencies
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level.upper()))

    # Set formatter
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Filter to only FlowMesh logs unless include_stdlib is True
    if not include_stdlib:
        # Set higher level for noisy libraries
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("fastapi").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class WorkflowLogContext:
    """Context manager for adding workflow context to logs.

    Usage:
        with WorkflowLogContext(workflow_id="abc123"):
            logger.info("Processing task")  # Will include workflow_id
    """

    def __init__(self, **context: Any) -> None:
        self._context = context
        self._filter = ContextFilter()

    def __enter__(self) -> WorkflowLogContext:
        """Set log context."""
        self._filter.set_context(**self._context)
        logging.getLogger().addFilter(self._filter)
        return self

    def __exit__(self, *args: Any) -> None:
        """Clear log context."""
        logging.getLogger().removeFilter(self._filter)
        self._filter.clear_context()
