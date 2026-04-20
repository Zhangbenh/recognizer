"""REGION_SELECT state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from infrastructure.config.sampling_config_repository import SamplingConfigRepository


class RegionSelectHandler(BaseStateHandler):
	def __init__(self, *, sampling_config_repository: SamplingConfigRepository) -> None:
		super().__init__(State.REGION_SELECT)
		self._sampling_config_repository = sampling_config_repository

	def on_enter(self, ctx: StateContext):
		map_id = ctx.selected_map_id or ""
		ctx.available_regions = self._sampling_config_repository.list_regions(map_id)
		if not ctx.available_regions:
			ctx.selected_region_index = None
			ctx.selected_region_id = None
			return []

		if ctx.selected_region_index is None or ctx.selected_region_index >= len(ctx.available_regions):
			ctx.selected_region_index = 0

		selected = ctx.available_regions[ctx.selected_region_index]
		ctx.selected_region_id = str(selected.get("region_id") or selected.get("id") or "") or None
		return []

