"""Domain service for querying sampling statistics snapshots."""

from __future__ import annotations

from sys import maxsize
from typing import Any

from domain.constants import DEFAULT_STATS_PAGE_SIZE
from domain.errors import DataError, StorageError
from domain.models import MapStatsItem, MapStatsSnapshot, StatsItem, StatsSnapshot
from infrastructure.config.label_repository import LabelRepository
from infrastructure.config.sampling_config_repository import SamplingConfigRepository
from infrastructure.storage.base_storage_adapter import BaseStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository


class StatisticsQueryService:
	"""Read sampling records and provide page-friendly snapshots."""

	def __init__(
		self,
		*,
		storage_adapter: BaseStorageAdapter | None = None,
		stats_repository: RegionStatsRepository | None = None,
		label_repository: LabelRepository | None = None,
		sampling_config_repository: SamplingConfigRepository | None = None,
		page_size: int = DEFAULT_STATS_PAGE_SIZE,
	) -> None:
		if stats_repository is None and storage_adapter is None:
			raise ValueError("Either storage_adapter or stats_repository must be provided")

		self._stats_repository = stats_repository
		self._storage_adapter = storage_adapter
		self._label_repository = label_repository or LabelRepository()
		self._sampling_config_repository = sampling_config_repository or SamplingConfigRepository()
		self._page_size = max(1, int(page_size))
		self._label_order_by_plant_key: dict[str, int] | None = None

	def snapshot_for_region(self, region_id: str) -> StatsSnapshot:
		if not region_id:
			return StatsSnapshot(region_id="", items=[], page_size=self._page_size)

		payload = self._safe_read()
		records = self._region_records(payload, region_id)
		items = self._build_region_items(records)
		items.sort(key=self._stats_sort_key)
		return StatsSnapshot(region_id=region_id, items=items, page_size=self._page_size)

	def snapshot_for_map(self, map_id: str) -> MapStatsSnapshot:
		if not map_id:
			return MapStatsSnapshot(map_id="", map_display_name="", items=[], page_size=self._page_size)

		payload = self._safe_read()
		map_item = self._safe_get_map(map_id)
		region_ids = self._map_region_ids(payload, map_id, map_item)
		region_name_by_id = self._map_region_display_names(map_item)
		aggregates: dict[str, dict[str, Any]] = {}
		recorded_region_count = 0

		for region_id in region_ids:
			records = self._region_records(payload, region_id)
			if records:
				recorded_region_count += 1
			for plant_key, raw in records.items():
				if not isinstance(raw, dict):
					continue
				resolved_plant_key = str(raw.get("plant_key") or plant_key)
				aggregate = aggregates.setdefault(
					resolved_plant_key,
					{
						"plant_key": resolved_plant_key,
						"display_name": str(raw.get("display_name") or raw.get("plant_name") or resolved_plant_key),
						"total_count": 0,
						"covered_regions": set(),
						"last_confidence": 0.0,
						"last_seen_at": "",
						"catalog_mapped": resolved_plant_key in self._label_order_map(),
					},
				)
				aggregate["total_count"] += int(raw.get("count", 0))
				aggregate["covered_regions"].add(region_id)
				last_seen_at = str(raw.get("last_seen_at") or "")
				if last_seen_at >= str(aggregate.get("last_seen_at") or ""):
					aggregate["last_seen_at"] = last_seen_at
					aggregate["last_confidence"] = float(raw.get("last_confidence", 0.0))

		items = [
			MapStatsItem(
				plant_key=str(item["plant_key"]),
				display_name=str(item["display_name"]),
				total_count=int(item["total_count"]),
				covered_region_count=len(item["covered_regions"]),
				covered_region_names=self._ordered_region_names(
					item["covered_regions"],
					region_ids,
					region_name_by_id,
				),
				last_confidence=float(item["last_confidence"]),
				catalog_mapped=bool(item["catalog_mapped"]),
			)
			for item in aggregates.values()
		]
		items.sort(key=self._map_stats_sort_key)

		map_display_name = map_id
		if isinstance(map_item, dict):
			map_display_name = str(map_item.get("display_name") or map_item.get("map_id") or map_id)

		return MapStatsSnapshot(
			map_id=map_id,
			map_display_name=map_display_name,
			total_region_count=len(region_ids),
			recorded_region_count=recorded_region_count,
			items=items,
			page_size=self._page_size,
		)

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

	def _build_region_items(self, records: dict[str, Any]) -> list[StatsItem]:
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
		return items

	def _stats_sort_key(self, item: StatsItem) -> tuple[int, int, str, str]:
		return self._sort_key(item.plant_key, item.display_name)

	def _map_stats_sort_key(self, item: MapStatsItem) -> tuple[int, int, str, str]:
		return self._sort_key(item.plant_key, item.display_name)

	def _sort_key(self, plant_key: str, display_name: str) -> tuple[int, int, str, str]:
		order = self._label_order_map().get(plant_key)
		return (
			0 if order is not None else 1,
			order if order is not None else maxsize,
			str(display_name),
			str(plant_key),
		)

	def _label_order_map(self) -> dict[str, int]:
		if self._label_order_by_plant_key is not None:
			return self._label_order_by_plant_key

		try:
			labels = self._label_repository.load()
		except Exception:
			self._label_order_by_plant_key = {}
			return self._label_order_by_plant_key

		order_map: dict[str, int] = {}
		for item in labels:
			if not isinstance(item, dict):
				continue
			plant_key = str(item.get("plant_key") or "").strip()
			index = item.get("index")
			if plant_key and isinstance(index, int):
				order_map[plant_key] = index

		self._label_order_by_plant_key = order_map
		return self._label_order_by_plant_key

	def _safe_get_map(self, map_id: str) -> dict[str, Any] | None:
		try:
			map_item = self._sampling_config_repository.get_map(map_id)
		except Exception:
			return None
		if not isinstance(map_item, dict):
			return None
		return map_item

	def _map_region_ids(self, payload: dict[str, Any], map_id: str, map_item: dict[str, Any] | None) -> list[str]:
		if isinstance(map_item, dict):
			regions = map_item.get("regions", [])
			if isinstance(regions, list):
				region_ids = [
					str(region.get("region_id")).strip()
					for region in regions
					if isinstance(region, dict) and str(region.get("region_id") or "").strip()
				]
				if region_ids:
					return region_ids

		regions = payload.get("regions", {})
		if not isinstance(regions, dict):
			return []

		prefix = f"{map_id}_"
		return [str(region_id) for region_id in regions.keys() if str(region_id).startswith(prefix)]

	def _map_region_display_names(self, map_item: dict[str, Any] | None) -> dict[str, str]:
		if not isinstance(map_item, dict):
			return {}

		regions = map_item.get("regions", [])
		if not isinstance(regions, list):
			return {}

		region_name_by_id: dict[str, str] = {}
		for region in regions:
			if not isinstance(region, dict):
				continue
			region_id = str(region.get("region_id") or "").strip()
			if not region_id:
				continue
			region_name_by_id[region_id] = str(region.get("display_name") or region_id).strip() or region_id
		return region_name_by_id

	def _ordered_region_names(
		self,
		covered_regions: set[str],
		ordered_region_ids: list[str],
		region_name_by_id: dict[str, str],
	) -> list[str]:
		if not covered_regions:
			return []

		ordered_names = [
			region_name_by_id.get(region_id, region_id)
			for region_id in ordered_region_ids
			if region_id in covered_regions
		]
		if ordered_names:
			return ordered_names

		return [region_name_by_id.get(region_id, region_id) for region_id in sorted(covered_regions)]

