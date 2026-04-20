"""Repository for region-scoped sampling statistics persistence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from infrastructure.storage.base_storage_adapter import BaseStorageAdapter


class RegionStatsRepository:
	"""Persistence helper for region-level sampling records.

	Storage shape:
	{
	  "regions": {
	    "<region_id>": {
	      "records": {
	        "<plant_key>": {...}
	      }
	    }
	  }
	}
	"""

	def __init__(self, *, storage_adapter: BaseStorageAdapter) -> None:
		self._storage_adapter = storage_adapter

	def load_all(self) -> dict[str, Any]:
		payload = self._storage_adapter.read(default_value={"regions": {}})
		if not isinstance(payload, dict):
			return {"regions": {}}

		regions = payload.get("regions")
		if not isinstance(regions, dict):
			payload["regions"] = {}

		return payload

	def save_all(self, payload: dict[str, Any]) -> None:
		self._storage_adapter.write(payload)

	def load_region_stats(self, region_id: str) -> dict[str, Any]:
		payload = self.load_all()
		regions = payload.get("regions", {})
		if not isinstance(regions, dict):
			return {"records": {}}

		region = regions.get(region_id, {"records": {}})
		if not isinstance(region, dict):
			return {"records": {}}

		records = region.get("records")
		if not isinstance(records, dict):
			region["records"] = {}

		return deepcopy(region)

	def save_region_stats(self, region_id: str, region_payload: dict[str, Any]) -> None:
		payload = self.load_all()
		regions = payload.setdefault("regions", {})
		if not isinstance(regions, dict):
			regions = {}
			payload["regions"] = regions

		regions[region_id] = deepcopy(region_payload)
		self.save_all(payload)
