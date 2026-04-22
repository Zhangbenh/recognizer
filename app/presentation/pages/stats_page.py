"""STATS page renderer."""

from __future__ import annotations

from typing import Any


class StatsPage:
	"""Render statistics snapshot page."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[区域统计]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append(f"  区域: {view_model.get('region_display_name') or view_model.get('region_id')}")

		error_message = view_model.get("stats_error_message")
		error_type = view_model.get("stats_error_type")
		if error_message:
			lines.append(f"  警告: {error_type}: {error_message}")

		page = int(view_model.get("page", 0)) + 1
		total_pages = int(view_model.get("total_pages", 1))
		lines.append(f"  页码: {page}/{max(total_pages, 1)}")

		items = view_model.get("items") or []
		if not items:
			lines.append("  统计项: <空>")
		else:
			lines.append("  统计项:")
			for index, item in enumerate(items, start=1):
				name = item.get("display_name")
				count = item.get("count")
				confidence = item.get("last_confidence")
				if isinstance(confidence, float):
					confidence_text = f"{confidence:.4f}"
				else:
					confidence_text = str(confidence)
				lines.append(f"    {index}. {name} | 次数={count} | 最近置信度={confidence_text}")

		lines.append(f"  操作: {view_model.get('hint')}")
		return lines

