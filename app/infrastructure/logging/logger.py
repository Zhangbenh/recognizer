"""Logger configuration helper for the recognizer runtime."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


def create_logger(
	name: str = "recognizer",
	*,
	level: str = "INFO",
	log_file: Optional[str] = None,
) -> logging.Logger:
	"""Create (or reuse) a configured logger instance."""

	logger = logging.getLogger(name)
	logger.setLevel(_parse_level(level))

	if logger.handlers:
		return logger

	formatter = logging.Formatter(
		fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)

	console_handler = logging.StreamHandler()
	console_handler.setFormatter(formatter)
	logger.addHandler(console_handler)

	if log_file:
		log_path = Path(log_file)
		log_path.parent.mkdir(parents=True, exist_ok=True)
		file_handler = logging.FileHandler(log_path, encoding="utf-8")
		file_handler.setFormatter(formatter)
		logger.addHandler(file_handler)

	logger.propagate = False
	return logger


def _parse_level(level: str) -> int:
	normalized = level.strip().upper()
	return {
		"DEBUG": logging.DEBUG,
		"INFO": logging.INFO,
		"WARNING": logging.WARNING,
		"ERROR": logging.ERROR,
		"CRITICAL": logging.CRITICAL,
	}.get(normalized, logging.INFO)

