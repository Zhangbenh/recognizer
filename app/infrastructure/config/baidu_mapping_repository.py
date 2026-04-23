"""Repository for Baidu name to local plant key mappings."""

from __future__ import annotations

import json
from pathlib import Path

from domain.errors import CloudConfigError


class BaiduMappingRepository:
	"""Load and query baidu_plant_mapping.json."""

	def __init__(self, file_path: str | None = None) -> None:
		self._file_path = Path(file_path) if file_path else self._default_file_path()

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> dict[str, str]:
		if not self._file_path.exists():
			raise CloudConfigError(f"baidu mapping file not found: {self._file_path}", retryable=True)

		try:
			with self._file_path.open("r", encoding="utf-8") as file:
				payload = json.load(file)
		except Exception as exc:
			raise CloudConfigError(f"baidu mapping file is invalid: {exc}", retryable=True) from exc

		if not isinstance(payload, dict):
			raise CloudConfigError("baidu_plant_mapping.json root must be an object", retryable=True)

		mappings = payload.get("mappings", {})
		if not isinstance(mappings, dict):
			raise CloudConfigError(
				"baidu_plant_mapping.json field 'mappings' must be an object",
				retryable=True,
			)

		result: dict[str, str] = {}
		for baidu_name, plant_key in mappings.items():
			if not isinstance(baidu_name, str) or not isinstance(plant_key, str):
				raise CloudConfigError(
					"baidu_plant_mapping.json mappings must be string-to-string",
					retryable=True,
				)
			normalized_name = self._normalize_name(baidu_name)
			normalized_key = plant_key.strip()
			if normalized_name and normalized_key:
				result[normalized_name] = normalized_key
		return result

	def plant_key_for(self, baidu_name: str) -> str | None:
		return self.load().get(self._normalize_name(baidu_name))

	@staticmethod
	def _normalize_name(value: str) -> str:
		return value.strip()

	@staticmethod
	def _default_file_path() -> Path:
		return Path(__file__).resolve().parents[3] / "config" / "baidu_plant_mapping.json"