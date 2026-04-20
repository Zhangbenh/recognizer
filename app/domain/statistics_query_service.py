"""Domain service for querying sampling statistics snapshots."""

from __future__ import annotations

from typing import Any

from domain.constants import DEFAULT_STATS_PAGE_SIZE
from domain.errors import DataError, StorageError
from domain.models import StatsItem, StatsSnapshot
from infrastructure.storage.base_storage_adapter import BaseStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository


class StatisticsQueryService:
	"""Read sampling records and provide page-friendly snapshots."""

	def __init__(
		self,
		*,
		storage_adapter: BaseStorageAdapter | None = None,
		stats_repository: RegionStatsRepository | None = None,
		page_size: int = DEFAULT_STATS_PAGE_SIZE,
	) -> None:
		if stats_repository is None and storage_adapter is None:
			raise ValueError("Either storage_adapter or stats_repository must be provided")

		self._stats_repository = stats_repository
		self._storage_adapter = storage_adapter
		self._page_size = max(1, int(page_size))

	def snapshot_for_region(self, region_id: str) -> StatsSnapshot:
		if not region_id:
			return StatsSnapshot(region_id="", items=[], page_size=self._page_size)

		payload = self._safe_read()
		records = self._region_records(payload, region_id)
		items: list[StatsItem] = []

		for plant_key, raw in records.items():
			if not isinstance(raw, dict):
				continue
			items.append(
				StatsItem(
					plant_key=str(raw.get("plant_key") or plant_key),
					plant_name=str(raw.get("plant_name") or plant_key),
					display_name=str(raw.get("display_name") or raw.get("plant_name") or plant_key),
					count=int(raw.get("count", 0)),
					last_confidence=float(raw.get("last_confidence", 0.0)),
					last_seen_at=str(raw.get("last_seen_at") or ""),
				)
			)

		items.sort(key=lambda item: item.display_name.lower())
		return StatsSnapshot(region_id=region_id, items=items, page_size=self._page_size)

	def _safe_read(self) -> dict[str, Any]:
		if self._stats_repository is not None:
			try:
				payload = self._stats_repository.load_all()
			except Exception as exc:
				raise StorageError(f"failed to read stats storage: {exc}", retryable=True) from exc

			if not isinstance(payload, dict):
				raise DataError("stats storage root must be object", retryable=False)
			return payload

		try:
			if self._storage_adapter is None:
				raise RuntimeError("storage adapter is not configured")
			payload = self._storage_adapter.read(default_value={})
		except Exception as exc:
			raise StorageError(f"failed to read stats storage: {exc}", retryable=True) from exc

		if not isinstance(payload, dict):
			raise DataError("stats storage root must be object", retryable=False)
		return payload

	def _region_records(self, payload: dict[str, Any], region_id: str) -> dict[str, Any]:
		regions = payload.get("regions", {})
		if not isinstance(regions, dict):
			raise DataError("stats storage 'regions' must be object", retryable=False)

		region = regions.get(region_id, {})
		if not isinstance(region, dict):
			return {}

		records = region.get("records", {})
		if not isinstance(records, dict):
			return {}

		return records

