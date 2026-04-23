"""Domain service for writing sampling recognition records."""

from __future__ import annotations

from typing import Any

from domain.errors import DataError
from domain.errors import StorageError
from domain.models import RecognitionResult, utc_now_iso
from infrastructure.storage.base_storage_adapter import BaseStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository


class SamplingRecorder:
	"""Persist recognized plants by region for sampling statistics."""

	def __init__(
		self,
		*,
		storage_adapter: BaseStorageAdapter | None = None,
		stats_repository: RegionStatsRepository | None = None,
	) -> None:
		if stats_repository is None and storage_adapter is None:
			raise ValueError("Either storage_adapter or stats_repository must be provided")

		self._stats_repository = stats_repository
		self._storage_adapter = storage_adapter

	def record(self, region_id: str, result: RecognitionResult) -> None:
		if not region_id:
			raise StorageError("region_id is required for recording", retryable=False)
		plant_key = str(result.plant_key or "").strip()
		if result.is_recognized and not plant_key:
			raise DataError("recognized result missing plant_key", retryable=False)
		if not result.is_recognized:
			return

		payload = self._safe_read()
		regions = payload.setdefault("regions", {})
		region_entry = regions.setdefault(region_id, {"records": {}})
		records = region_entry.setdefault("records", {})

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
		region = self._safe_load_region(region_id)
		records = region.get("records", {})
		if not isinstance(records, dict):
			return {}
		return records

	def _safe_load_region(self, region_id: str) -> dict[str, Any]:
		if self._stats_repository is not None:
			try:
				return self._stats_repository.load_region_stats(region_id)
			except Exception as exc:
				raise StorageError(f"load region stats failed: {exc}", retryable=True) from exc

		payload = self._safe_read()
		regions = payload.get("regions", {})
		if not isinstance(regions, dict):
			return {"records": {}}
		region = regions.get(region_id, {"records": {}})
		if not isinstance(region, dict):
			return {"records": {}}
		return region

	def _safe_read(self) -> dict[str, Any]:
		if self._stats_repository is not None:
			try:
				return self._stats_repository.load_all()
			except Exception as exc:
				raise StorageError(f"read sampling data failed: {exc}", retryable=True) from exc

		try:
			if self._storage_adapter is None:
				raise RuntimeError("storage adapter is not configured")
			data = self._storage_adapter.read(default_value={})
		except Exception as exc:
			raise StorageError(f"read sampling data failed: {exc}", retryable=True) from exc

		if not isinstance(data, dict):
			return {}
		return data

	def _safe_write(self, payload: dict[str, Any]) -> None:
		if self._stats_repository is not None:
			try:
				self._stats_repository.save_all(payload)
			except Exception as exc:
				raise StorageError(f"write sampling data failed: {exc}", retryable=True) from exc
			return

		try:
			if self._storage_adapter is None:
				raise RuntimeError("storage adapter is not configured")
			self._storage_adapter.write(payload)
		except Exception as exc:
			raise StorageError(f"write sampling data failed: {exc}", retryable=True) from exc

