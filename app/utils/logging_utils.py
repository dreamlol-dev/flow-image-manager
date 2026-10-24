"""
logging_utils.py — Application logging configuration.
Sets up rotating file logs under the logs/ directory with optional
console output. Verbosity is controlled via settings.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


_APP_NAME = "FlowImageManager"
_LOG_DIR: Path | None = None
_initialized = False


def setup_logging(log_dir: Path, verbosity: str = "INFO") -> logging.Logger:
    """
    Initialize application logging.

    Args:
        log_dir: Directory for log files.
        verbosity: Log level name ("DEBUG", "INFO", "WARNING", "ERROR").

    Returns:
        Root logger for the application.
    """
    global _LOG_DIR, _initialized
    _LOG_DIR = log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, verbosity.upper(), logging.INFO)

    logger = logging.getLogger(_APP_NAME)
    logger.setLevel(level)

    if _initialized:
        return logger

    # Rotating file handler (5 MB × 5 backups)
    log_file = log_dir / "flow_image_manager.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_detailed_formatter())
    logger.addHandler(file_handler)

    # Console handler (INFO+)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(_simple_formatter())
    logger.addHandler(console_handler)

    _initialized = True
    logger.info("Logging initialized. Log file: %s", log_file)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """
    Return a child logger under the application namespace.

    Args:
        name: Sub-module name suffix.
    """
    full_name = f"{_APP_NAME}.{name}" if name else _APP_NAME
    return logging.getLogger(full_name)


def set_verbosity(verbosity: str) -> None:
    """Update the log level on all handlers of the application logger."""
    level = getattr(logging, verbosity.upper(), logging.INFO)
    logger = logging.getLogger(_APP_NAME)
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)


def get_log_dir() -> Path | None:
    """Return the configured log directory path."""
    return _LOG_DIR


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _detailed_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _simple_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

