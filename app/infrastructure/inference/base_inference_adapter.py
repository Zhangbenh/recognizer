"""Abstract inference adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InferenceOutput:
	"""Normalized output from inference runtime."""

	class_id: int
	confidence: float
	top3: list[tuple[int, float]] = field(default_factory=list)
	probabilities: list[float] = field(default_factory=list)


class BaseInferenceAdapter(ABC):
	"""Abstract adapter for model loading and model invocation."""

	@abstractmethod
	def load_model(self, model_path: str) -> None:
		"""Load and initialize model runtime resources."""

	@abstractmethod
	def infer(self, image: Any) -> InferenceOutput:
		"""Run inference and return normalized output."""

	@abstractmethod
	def close(self) -> None:
		"""Release interpreter/runtime resources."""

	@property
	@abstractmethod
	def is_loaded(self) -> bool:
		"""Return whether a model has been loaded and is ready."""

