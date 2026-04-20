"""STATS page renderer."""

from __future__ import annotations

from typing import Any


class StatsPage:
	"""Render statistics snapshot page."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Stats]"]
		lines.append(f"  mode: {view_model.get('mode')}")
		lines.append(f"  region_id: {view_model.get('region_id')}")

		page = int(view_model.get("page", 0)) + 1
		total_pages = int(view_model.get("total_pages", 1))
		lines.append(f"  page: {page}/{max(total_pages, 1)}")

		items = view_model.get("items") or []
		if not items:
			lines.append("  items: <empty>")
		else:
			lines.append("  items:")
			for index, item in enumerate(items, start=1):
				name = item.get("display_name")
				count = item.get("count")
				confidence = item.get("last_confidence")
				if isinstance(confidence, float):
					confidence_text = f"{confidence:.4f}"
				else:
					confidence_text = str(confidence)
				lines.append(f"    {index}. {name} | count={count} | last_confidence={confidence_text}")

		lines.append("  actions: NAV next page | BACK_LONG region")
		return lines

