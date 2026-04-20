"""MAP_SELECT state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from infrastructure.config.sampling_config_repository import SamplingConfigRepository


class MapSelectHandler(BaseStateHandler):
	def __init__(self, *, sampling_config_repository: SamplingConfigRepository) -> None:
		super().__init__(State.MAP_SELECT)
		self._sampling_config_repository = sampling_config_repository

	def on_enter(self, ctx: StateContext):
		ctx.available_maps = self._sampling_config_repository.list_maps()
		if not ctx.available_maps:
			ctx.selected_map_index = None
			ctx.selected_map_id = None
			return []

		if ctx.selected_map_index is None or ctx.selected_map_index >= len(ctx.available_maps):
			ctx.selected_map_index = 0

		selected = ctx.available_maps[ctx.selected_map_index]
		ctx.selected_map_id = str(selected.get("map_id") or selected.get("id") or "") or None
		return []

