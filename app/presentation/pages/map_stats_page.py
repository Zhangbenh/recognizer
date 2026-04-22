"""MAP_STATS page renderer."""

from __future__ import annotations

from typing import Any


class MapStatsPage:
	"""Render map-level aggregated statistics page."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[地图统计]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append(f"  地图: {view_model.get('map_display_name') or view_model.get('map_id')}")
		lines.append(f"  区域总数: {view_model.get('total_region_count', 0)}")
		lines.append(f"  已记录区域: {view_model.get('recorded_region_count', 0)}")
		lines.append(f"  植物种类: {view_model.get('plant_species_count', 0)}")

		error_message = view_model.get("map_stats_error_message")
		error_type = view_model.get("map_stats_error_type")
		if error_message:
			lines.append(f"  警告: {error_type}: {error_message}")

		page = int(view_model.get("page", 0)) + 1
		total_pages = int(view_model.get("total_pages", 1))
		lines.append(f"  页码: {page}/{max(total_pages, 1)}")

		items = view_model.get("items") or []
		if not items:
			lines.append("  聚合项: <空>")
		else:
			lines.append("  聚合项:")
			for index, item in enumerate(items, start=1):
				name = item.get("display_name")
				total_count = item.get("total_count")
				covered_region_count = item.get("covered_region_count")
				catalog_mapped = "是" if item.get("catalog_mapped") else "否"
				confidence = item.get("last_confidence")
				if isinstance(confidence, float):
					confidence_text = f"{confidence:.4f}"
				else:
					confidence_text = str(confidence)
				lines.append(
					f"    {index}. {name} | 总次数={total_count} | 覆盖区域={covered_region_count} | 最近置信度={confidence_text} | 已映射={catalog_mapped}"
				)

		lines.append(f"  操作: {view_model.get('hint')}")
		return lines