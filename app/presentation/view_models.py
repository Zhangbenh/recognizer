"""View-model builders for renderer output."""

from __future__ import annotations

from typing import Any

from application.state_context import StateContext
from application.states import State
from domain.errors import CameraError, DataError, InferenceError, StorageError


def _selected_display_name(items: list[dict[str, Any]], selected_id: str | None, id_key: str) -> str | None:
	for item in items:
		if str(item.get(id_key) or "") == str(selected_id or ""):
			name = item.get("display_name")
			if isinstance(name, str) and name:
				return name
	return None


def _available_display_names(items: list[dict[str, Any]]) -> list[str]:
	names: list[str] = []
	for item in items:
		name = item.get("display_name")
		if isinstance(name, str) and name:
			names.append(name)
	return names


def _is_non_fatal_error(error_type: str | None) -> bool:
	if not error_type:
		return False
	return error_type in {
		CameraError.__name__,
		DataError.__name__,
		StorageError.__name__,
		InferenceError.__name__,
	}


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
		selected_name = _selected_display_name(ctx.available_maps, ctx.selected_map_id, "map_id")
		base.update(
			{
				"selected_map_id": ctx.selected_map_id,
				"selected_map_index": ctx.selected_map_index,
				"map_count": len(ctx.available_maps),
				"selected_map_display_name": selected_name,
				"available_map_names": _available_display_names(ctx.available_maps),
			}
		)
	elif state == State.REGION_SELECT:
		selected_map_name = _selected_display_name(ctx.available_maps, ctx.selected_map_id, "map_id")
		selected_region_name = _selected_display_name(ctx.available_regions, ctx.selected_region_id, "region_id")
		base.update(
			{
				"selected_map_id": ctx.selected_map_id,
				"selected_map_display_name": selected_map_name,
				"selected_region_id": ctx.selected_region_id,
				"selected_region_index": ctx.selected_region_index,
				"region_count": len(ctx.available_regions),
				"selected_region_display_name": selected_region_name,
				"available_region_names": _available_display_names(ctx.available_regions),
			}
		)
	elif state == State.PREVIEW:
		if ctx.mode == "sampling":
			selected_map_name = _selected_display_name(ctx.available_maps, ctx.selected_map_id, "map_id")
			selected_region_name = _selected_display_name(ctx.available_regions, ctx.selected_region_id, "region_id")
			base.update(
				{
					"selected_map_id": ctx.selected_map_id,
					"selected_map_display_name": selected_map_name,
					"selected_region_id": ctx.selected_region_id,
					"selected_region_display_name": selected_region_name,
					"hint": "CONFIRM: capture | BACK_LONG: return",
				}
			)
		else:
			base.update({"hint": "CONFIRM: capture | BACK_LONG: return"})

		error = ctx.last_error
		if error and _is_non_fatal_error(error.error_type) and ctx.preview_error_flash_pending:
			base.update(
				{
					"non_fatal_error_type": error.error_type,
					"non_fatal_error_message": error.message,
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
			error = ctx.last_error
			if error and _is_non_fatal_error(error.error_type):
				base.update(
					{
						"stats_error_type": error.error_type,
						"stats_error_message": error.message,
					}
				)
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
	elif state == State.RECORDING:
		result = ctx.last_recognition_result
		base.update(
			{
				"selected_region_id": ctx.selected_region_id,
				"display_name": result.display_name if result else None,
				"plant_name": result.plant_name if result else None,
				"confidence": result.confidence if result else None,
				"is_recognized": result.is_recognized if result else False,
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

