"""Abstract camera adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCameraAdapter(ABC):
	"""Abstract camera adapter used by application handlers/services."""

	@abstractmethod
	def start(self) -> None:
		"""Start camera capture pipeline."""

	@abstractmethod
	def stop(self) -> None:
		"""Stop camera capture pipeline."""

	@abstractmethod
	def capture_frame(self) -> Any:
		"""Capture one frame and return an RGB-like array."""

	@abstractmethod
	def close(self) -> None:
		"""Release all resources owned by the adapter."""

	@property
	@abstractmethod
	def is_started(self) -> bool:
		"""Return whether camera pipeline has started."""

