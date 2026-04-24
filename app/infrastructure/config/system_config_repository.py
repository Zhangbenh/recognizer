"""Repository for runtime system configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SystemConfigRepository:
	"""Load and query system_config.json."""

	def __init__(self, file_path: str | None = None) -> None:
		self._file_path = Path(file_path) if file_path else self._default_file_path()

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> dict[str, Any]:
		if not self._file_path.exists():
			raise FileNotFoundError(f"system config not found: {self._file_path}")
		with self._file_path.open("r", encoding="utf-8") as file:
			payload = json.load(file)
		if not isinstance(payload, dict):
			raise ValueError("system_config.json root must be an object")
		return payload

	def get(self, key: str, default: Any = None) -> Any:
		return self.load().get(key, default)

	def ui_language(self) -> str:
		return str(self.get("ui_language", "zh-CN"))

	def recognition_strategy(self) -> str:
		return str(self.get("recognition_strategy", "local_only"))

	def cloud_request_timeout_s(self) -> float:
		return float(self.get("cloud_request_timeout_s", self.infer_timeout_s()))

	def local_infer_timeout_s(self) -> float:
		return float(self.get("local_infer_timeout_s", self.infer_timeout_s()))

	def recognition_threshold(self) -> float:
		return float(self.get("recognition_threshold", 0.6))

	def cloud_recognition_threshold(self) -> float:
		return float(self.get("cloud_recognition_threshold", self.recognition_threshold()))

	def boot_splash_duration_s(self) -> float:
		return float(self.get("boot_splash_duration_s", 3.0))

	def display_timeout_s(self) -> float:
		return float(self.get("display_timeout_s", 5.0))

	def infer_timeout_s(self) -> float:
		return float(self.get("infer_timeout_s", 3.0))

	def record_timeout_s(self) -> float:
		return float(self.get("record_timeout_s", 1.0))

	def capture_debounce_ms(self) -> int:
		return int(self.get("capture_debounce_ms", 100))

	def long_press_threshold_ms(self) -> int:
		return int(self.get("long_press_threshold_ms", 800))

	def release_gate(self) -> dict[str, Any]:
		data = self.get("release_gate", {})
		if not isinstance(data, dict):
			return {}
		return data

	def performance_budget(self) -> dict[str, Any]:
		data = self.get("performance_budget", {})
		if not isinstance(data, dict):
			return {}
		return data

	@staticmethod
	def _default_file_path() -> Path:
		return Path(__file__).resolve().parents[3] / "config" / "system_config.json"

