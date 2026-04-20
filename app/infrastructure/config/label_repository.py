"""Repository for labels configuration."""

from __future__ import annotations

import json
from pathlib import Path


class LabelRepository:
	"""Load and query labels.json."""

	def __init__(self, file_path: str | None = None) -> None:
		self._file_path = Path(file_path) if file_path else self._default_file_path()

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> list[dict]:
		payload = self._read_json()
		labels = payload.get("labels", [])
		if not isinstance(labels, list):
			raise ValueError("labels.json field 'labels' must be a list")
		return labels

	def index_map(self) -> dict[int, dict]:
		result: dict[int, dict] = {}
		for item in self.load():
			index = item.get("index")
			if not isinstance(index, int):
				continue
			result[index] = item
		return result

	def display_name_for(self, class_id: int) -> str | None:
		entry = self.index_map().get(class_id)
		if not entry:
			return None
		return entry.get("display_name") or entry.get("plant_name")

	def _read_json(self) -> dict:
		if not self._file_path.exists():
			raise FileNotFoundError(f"labels file not found: {self._file_path}")
		with self._file_path.open("r", encoding="utf-8") as file:
			payload = json.load(file)
		if not isinstance(payload, dict):
			raise ValueError("labels.json root must be an object")
		return payload

	@staticmethod
	def _default_file_path() -> Path:
		return Path(__file__).resolve().parents[3] / "config" / "labels.json"

