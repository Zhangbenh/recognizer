"""Abstract storage adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseStorageAdapter(ABC):
	"""Abstract storage adapter used by domain services."""

	@abstractmethod
	def read(self, default_value: Any | None = None) -> Any:
		"""Read and deserialize persistent data."""

	@abstractmethod
	def write(self, data: Any) -> None:
		"""Serialize and persist data."""

	@abstractmethod
	def exists(self) -> bool:
		"""Return whether storage file/object currently exists."""

