"""Repository for sampling maps/regions configuration."""

from __future__ import annotations

import json
from pathlib import Path


class SamplingConfigRepository:
	"""Load and query sampling_config.json."""

	def __init__(self, file_path: str | None = None) -> None:
		self._file_path = Path(file_path) if file_path else self._default_file_path()

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> dict:
		if not self._file_path.exists():
			raise FileNotFoundError(f"sampling config not found: {self._file_path}")
		with self._file_path.open("r", encoding="utf-8") as file:
			payload = json.load(file)
		if not isinstance(payload, dict):
			raise ValueError("sampling_config.json root must be an object")
		return payload

	def list_maps(self) -> list[dict]:
		payload = self.load()
		maps = payload.get("maps", [])
		if not isinstance(maps, list):
			raise ValueError("sampling_config.json field 'maps' must be a list")
		return maps

	def get_map(self, map_id: str) -> dict | None:
		for map_item in self.list_maps():
			if str(map_item.get("map_id")) == map_id:
				return map_item
		return None

	def list_regions(self, map_id: str) -> list[dict]:
		map_item = self.get_map(map_id)
		if not map_item:
			return []
		regions = map_item.get("regions", [])
		if not isinstance(regions, list):
			return []
		return regions

	@staticmethod
	def _default_file_path() -> Path:
		return Path(__file__).resolve().parents[3] / "config" / "sampling_config.json"

