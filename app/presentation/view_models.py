"""View-model builders for renderer output."""

from __future__ import annotations

from typing import Any

from application.state_context import StateContext
from application.states import State


def build_view_model(state: State, ctx: StateContext) -> dict[str, Any]:
	base: dict[str, Any] = {
		"state": state.value,
		"mode": ctx.mode,
	}

	if state == State.HOME:
		base.update(
			{
				"selected_home_option": ctx.selected_home_option,
				"hint": "NAV: switch option | CONFIRM: enter",
			}
		)
	elif state == State.MAP_SELECT:
		base.update(
			{
				"selected_map_id": ctx.selected_map_id,
				"selected_map_index": ctx.selected_map_index,
				"map_count": len(ctx.available_maps),
			}
		)
	elif state == State.REGION_SELECT:
		base.update(
			{
				"selected_map_id": ctx.selected_map_id,
				"selected_region_id": ctx.selected_region_id,
				"selected_region_index": ctx.selected_region_index,
				"region_count": len(ctx.available_regions),
			}
		)
	elif state == State.PREVIEW:
		base.update(
			{
				"selected_map_id": ctx.selected_map_id,
				"selected_region_id": ctx.selected_region_id,
				"hint": "CONFIRM: capture | BACK_LONG: return",
			}
		)
	elif state == State.DISPLAY:
		result = ctx.last_recognition_result
		base.update(
			{
				"display_name": result.display_name if result else None,
				"plant_name": result.plant_name if result else None,
				"confidence": result.confidence if result else None,
				"is_recognized": result.is_recognized if result else False,
			}
		)
	elif state == State.STATS:
		snapshot = ctx.current_stats_snapshot
		if snapshot is None:
			base.update({"region_id": ctx.selected_region_id, "items": [], "page": 0, "total_pages": 1})
		else:
			page_index = max(0, ctx.selected_stats_page_index)
			page_items = [
				{
					"display_name": item.display_name,
					"count": item.count,
					"last_confidence": item.last_confidence,
				}
				for item in snapshot.page(page_index)
			]
			base.update(
				{
					"region_id": snapshot.region_id,
					"page": page_index,
					"total_pages": snapshot.total_pages,
					"items": page_items,
				}
			)
	elif state == State.ERROR:
		error = ctx.last_error
		base.update(
			{
				"error_type": error.error_type if error else None,
				"error_message": error.message if error else None,
				"retryable": bool(error and error.retryable),
				"hint": "CONFIRM: retry",
			}
		)

	return base

