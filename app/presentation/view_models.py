"""View-model builders for renderer output."""

from __future__ import annotations

from typing import Any

from application.state_context import StateContext
from application.states import State
from domain.errors import CameraError, DataError, InferenceError, StorageError


def _mode_display_name(mode: str | None) -> str:
	if mode == "sampling":
		return "采样模式"
	return "普通模式"


def _home_option_display_name(option: str | None) -> str:
	if option == "sampling":
		return "采样统计"
	return "普通识别"


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


def _selected_value(items: list[dict[str, Any]], selected_id: str | None, id_key: str, field: str) -> Any:
	for item in items:
		if str(item.get(id_key) or "") == str(selected_id or ""):
			return item.get(field)
	return None


def _recognition_source_display_name(result: Any | None) -> str | None:
	if result is None:
		return None

	source = str(getattr(result, "source", "") or "").strip().lower()
	fallback_used = bool(getattr(result, "fallback_used", False))
	if source == "cloud":
		return "云端"
	if source == "local" and fallback_used:
		return "本地回退"
	if source == "local":
		return "本地"
	return source or None


def _selection_items(items: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
	result: list[dict[str, Any]] = []
	for item in items:
		item_id = str(item.get(id_key) or item.get("id") or "").strip()
		if not item_id:
			continue
		result.append(
			{
				"id": item_id,
				"display_name": str(item.get("display_name") or item_id),
				"thumbnail_path": item.get("thumbnail_path"),
			}
		)
	return result


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
		"mode_display_name": _mode_display_name(ctx.mode),
	}

	if state == State.BOOTING:
		base.update(
			{
				"title": "植物识别系统",
				"status": "启动中",
				"hint": "正在初始化相机与模型...",
			}
		)
	elif state == State.HOME:
		base.update(
			{
				"selected_home_option": ctx.selected_home_option,
				"selected_home_option_display_name": _home_option_display_name(ctx.selected_home_option),
				"hint": "NAV：切换模式 | CONFIRM：进入",
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
				"selected_map_thumbnail_path": _selected_value(ctx.available_maps, ctx.selected_map_id, "map_id", "thumbnail_path"),
				"map_items": _selection_items(ctx.available_maps, "map_id"),
				"hint": "NAV：切换地图 | CONFIRM：进入区域 | NAV_LONG：地图统计 | BACK_LONG：返回首页",
			}
		)
	elif state == State.MAP_STATS:
		snapshot = ctx.current_map_stats_snapshot
		selected_map_name = _selected_display_name(ctx.available_maps, ctx.selected_map_id, "map_id")
		selected_map_thumbnail_path = _selected_value(ctx.available_maps, ctx.selected_map_id, "map_id", "thumbnail_path")
		if snapshot is None:
			base.update(
				{
					"map_id": ctx.selected_map_id,
					"map_display_name": selected_map_name,
					"map_thumbnail_path": selected_map_thumbnail_path,
					"total_region_count": 0,
					"recorded_region_count": 0,
					"plant_species_count": 0,
					"page": 0,
					"total_pages": 1,
					"items": [],
					"hint": "NAV：下一页 | BACK_LONG：返回地图",
				}
			)
			error = ctx.last_error
			if error and _is_non_fatal_error(error.error_type):
				base.update(
					{
						"map_stats_error_type": error.error_type,
						"map_stats_error_message": error.message,
					}
				)
		else:
			page_index = max(0, ctx.selected_map_stats_page_index)
			page_items = [
				{
					"display_name": item.display_name,
					"total_count": item.total_count,
					"covered_region_count": item.covered_region_count,
					"last_confidence": item.last_confidence,
					"catalog_mapped": item.catalog_mapped,
				}
				for item in snapshot.page(page_index)
			]
			base.update(
				{
					"map_id": snapshot.map_id,
					"map_display_name": snapshot.map_display_name,
					"map_thumbnail_path": selected_map_thumbnail_path,
					"total_region_count": snapshot.total_region_count,
					"recorded_region_count": snapshot.recorded_region_count,
					"plant_species_count": snapshot.plant_species_count,
					"page": page_index,
					"total_pages": snapshot.total_pages,
					"items": page_items,
					"hint": "NAV：下一页 | BACK_LONG：返回地图",
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
				"selected_region_thumbnail_path": _selected_value(ctx.available_regions, ctx.selected_region_id, "region_id", "thumbnail_path"),
				"region_items": _selection_items(ctx.available_regions, "region_id"),
				"hint": "NAV：切换区域 | CONFIRM：进入预览 | NAV_LONG：区域统计 | BACK_LONG：返回地图",
			}
		)
	elif state == State.PREVIEW:
		result = ctx.last_recognition_result
		if ctx.mode == "sampling":
			selected_map_name = _selected_display_name(ctx.available_maps, ctx.selected_map_id, "map_id")
			selected_region_name = _selected_display_name(ctx.available_regions, ctx.selected_region_id, "region_id")
			base.update(
				{
					"selected_map_id": ctx.selected_map_id,
					"selected_map_display_name": selected_map_name,
					"selected_region_id": ctx.selected_region_id,
					"selected_region_display_name": selected_region_name,
					"hint": "CONFIRM：拍摄 | BACK_LONG：返回",
				}
			)
		else:
			base.update({"hint": "CONFIRM：拍摄 | BACK_LONG：返回"})

		if result is not None:
			base.update(
				{
					"last_recognition_display_name": result.display_name or "未识别",
					"last_recognition_source_display_name": _recognition_source_display_name(result),
					"last_recognition_is_recognized": bool(result.is_recognized),
				}
			)

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
				"hint": "BACK_LONG：返回" if ctx.mode == "normal" else "等待自动流转...",
				"display_name": result.display_name if result else None,
				"plant_name": result.plant_name if result else None,
				"confidence": result.confidence if result else None,
				"is_recognized": result.is_recognized if result else False,
				"source_display_name": _recognition_source_display_name(result),
			}
		)
	elif state == State.CAPTURED:
		base.update(
			{
				"status": "已拍摄",
				"hint": "当前画面已冻结",
			}
		)
	elif state == State.INFERENCING:
		base.update(
			{
				"status": "识别中",
				"hint": "AI 正在识别...",
			}
		)
	elif state == State.STATS:
		snapshot = ctx.current_stats_snapshot
		selected_region_name = _selected_display_name(ctx.available_regions, ctx.selected_region_id, "region_id")
		if snapshot is None:
			base.update(
				{
					"region_id": ctx.selected_region_id,
					"region_display_name": selected_region_name,
					"items": [],
					"page": 0,
					"total_pages": 1,
					"hint": "NAV：下一页 | BACK_LONG：返回区域",
				}
			)
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
					"region_display_name": selected_region_name,
					"page": page_index,
					"total_pages": snapshot.total_pages,
					"items": page_items,
					"hint": "NAV：下一页 | BACK_LONG：返回区域",
				}
			)
	elif state == State.RECORDING:
		result = ctx.last_recognition_result
		base.update(
			{
				"status": "记录中",
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
				"hint": "CONFIRM：重试",
			}
		)

	return base

