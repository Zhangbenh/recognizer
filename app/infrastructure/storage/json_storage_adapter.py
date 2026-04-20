"""JSON storage adapter with atomic write semantics."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from infrastructure.storage.base_storage_adapter import BaseStorageAdapter


class JsonStorageAdapter(BaseStorageAdapter):
	"""Persist JSON data atomically and recover safely from corruption."""

	def __init__(self, file_path: str, *, default_value: Any = None, pretty: bool = True) -> None:
		self._path = Path(file_path)
		self._tmp_path = Path(f"{file_path}.tmp")
		self._default_value = {} if default_value is None else default_value
		self._pretty = pretty

	@property
	def file_path(self) -> Path:
		return self._path

	def read(self, default_value: Any | None = None) -> Any:
		fallback = self._default_value if default_value is None else default_value

		if not self._path.exists():
			return copy.deepcopy(fallback)

		try:
			with self._path.open("r", encoding="utf-8") as file:
				return json.load(file)
		except json.JSONDecodeError:
			return copy.deepcopy(fallback)

	def write(self, data: Any) -> None:
		self._path.parent.mkdir(parents=True, exist_ok=True)

		if self._pretty:
			json_text = json.dumps(data, ensure_ascii=False, indent=2)
		else:
			json_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

		with self._tmp_path.open("w", encoding="utf-8") as file:
			file.write(json_text)
			file.flush()
			os.fsync(file.fileno())

		os.replace(self._tmp_path, self._path)

	def exists(self) -> bool:
		return self._path.exists()

