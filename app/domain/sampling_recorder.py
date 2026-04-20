"""Domain service for writing sampling recognition records."""

from __future__ import annotations

from typing import Any

from domain.errors import StorageError
from domain.models import RecognitionResult, utc_now_iso
from infrastructure.storage.base_storage_adapter import BaseStorageAdapter


class SamplingRecorder:
	"""Persist recognized plants by region for sampling statistics."""

	def __init__(self, *, storage_adapter: BaseStorageAdapter) -> None:
		self._storage_adapter = storage_adapter

	def record(self, region_id: str, result: RecognitionResult) -> None:
		if not region_id:
			raise StorageError("region_id is required for recording", retryable=False)
		if not result.is_recognized or not result.plant_key:
			return

		payload = self._safe_read()
		regions = payload.setdefault("regions", {})
		region_entry = regions.setdefault(region_id, {"records": {}})
		records = region_entry.setdefault("records", {})

		plant_key = result.plant_key
		entry = records.setdefault(
			plant_key,
			{
				"plant_key": plant_key,
				"plant_name": result.plant_name or plant_key,
				"display_name": result.display_name or result.plant_name or plant_key,
				"count": 0,
				"last_confidence": 0.0,
				"last_seen_at": utc_now_iso(),
			},
		)

		entry["count"] = int(entry.get("count", 0)) + 1
		entry["last_confidence"] = float(result.confidence)
		entry["last_seen_at"] = utc_now_iso()
		entry["plant_name"] = result.plant_name or entry.get("plant_name", plant_key)
		entry["display_name"] = result.display_name or entry.get("display_name", plant_key)

		self._safe_write(payload)

	def region_records(self, region_id: str) -> dict[str, Any]:
		payload = self._safe_read()
		regions = payload.get("regions", {})
		if not isinstance(regions, dict):
			return {}
		region = regions.get(region_id, {})
		if not isinstance(region, dict):
			return {}
		records = region.get("records", {})
		if not isinstance(records, dict):
			return {}
		return records

	def _safe_read(self) -> dict[str, Any]:
		try:
			data = self._storage_adapter.read(default_value={})
		except Exception as exc:
			raise StorageError(f"read sampling data failed: {exc}", retryable=True) from exc

		if not isinstance(data, dict):
			return {}
		return data

	def _safe_write(self, payload: dict[str, Any]) -> None:
		try:
			self._storage_adapter.write(payload)
		except Exception as exc:
			raise StorageError(f"write sampling data failed: {exc}", retryable=True) from exc

