"""MAP_STATS state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.statistics_query_service import StatisticsQueryService


class MapStatsHandler(BaseStateHandler):
	def __init__(self, *, statistics_query_service: StatisticsQueryService) -> None:
		super().__init__(State.MAP_STATS)
		self._statistics_query_service = statistics_query_service

	def on_enter(self, ctx: StateContext):
		try:
			snapshot = self._statistics_query_service.snapshot_for_map(ctx.selected_map_id or "")
		except Exception as exc:
			ctx.set_error(exc)
			ctx.current_map_stats_snapshot = None
			return []

		ctx.current_map_stats_snapshot = snapshot
		if ctx.selected_map_stats_page_index >= snapshot.total_pages:
			ctx.selected_map_stats_page_index = 0
		return []