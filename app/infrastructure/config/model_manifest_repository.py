"""Repository for model manifest configuration."""

from __future__ import annotations

import json
from pathlib import Path

from domain.errors import ModelError


class ModelManifestRepository:
	"""Load and validate model_manifest.json."""

	def __init__(self, file_path: str | None = None) -> None:
		self._file_path = Path(file_path) if file_path else self._default_file_path()

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> dict:
		if not self._file_path.exists():
			raise ModelError(f"model manifest not found: {self._file_path}", retryable=True)

		try:
			with self._file_path.open("r", encoding="utf-8") as file:
				payload = json.load(file)
		except Exception as exc:
			raise ModelError(f"model manifest is invalid: {exc}", retryable=True) from exc

		if not isinstance(payload, dict):
			raise ModelError("model_manifest.json root must be an object", retryable=True)
		return payload

	def get_model_file(self) -> str:
		payload = self.load()
		model_file = payload.get("model_file")
		if not isinstance(model_file, str) or not model_file:
			raise ModelError("model_manifest.json missing non-empty 'model_file'", retryable=True)
		return model_file

	def resolve_model_path(self, models_dir: str | None = None) -> Path:
		model_file = self.get_model_file()
		if models_dir:
			base = Path(models_dir)
		else:
			base = Path(__file__).resolve().parents[3] / "models"
		return base / model_file

	def output_classes(self) -> int:
		payload = self.load()
		value = payload.get("output_classes")
		if not isinstance(value, int):
			raise ModelError("model_manifest.json missing integer 'output_classes'", retryable=True)
		return value

	def evaluated_top1_accuracy(self) -> float:
		payload = self.load()
		value = payload.get("evaluated_top1_accuracy", 0.0)
		return float(value)

	def validate_release_gate(self, min_top1_accuracy: float, required_output_classes: int) -> bool:
		payload = self.load()
		model_acc = float(payload.get("evaluated_top1_accuracy", 0.0))
		model_classes = int(payload.get("output_classes", -1))
		return model_acc >= min_top1_accuracy and model_classes == required_output_classes

	@staticmethod
	def _default_file_path() -> Path:
		return Path(__file__).resolve().parents[3] / "config" / "model_manifest.json"

