"""Shared logging configuration for CLI runners/collectors.

All entry points (`src.live.runner`, `src.collector.runner`,
`src.backtester.engine`) call `configure_logging(path)` in their `main()`
so INFO-level output goes to stderr and is appended to a file under
`logs/` for post-hoc inspection.
"""

from __future__ import annotations

import logging
import os
import sys

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


def configure_logging(log_path: str, *, level: int = logging.INFO) -> None:
    """Route root logging to both stderr and `log_path` (append mode)."""
    dirname = os.path.dirname(log_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)
    # Idempotent: drop existing handlers so repeat invocations don't duplicate lines.
    for h in list(root.handlers):
        root.removeHandler(h)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
