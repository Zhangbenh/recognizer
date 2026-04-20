"""Abstract input adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseInputAdapter(ABC):
	"""Abstract adapter that reads user inputs and emits raw events."""

	@abstractmethod
	def poll_raw_inputs(self) -> list[Any]:
		"""Poll currently available raw inputs without blocking indefinitely."""

	@abstractmethod
	def close(self) -> None:
		"""Release underlying input resources."""

