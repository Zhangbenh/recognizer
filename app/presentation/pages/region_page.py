"""REGION_SELECT page renderer."""

from __future__ import annotations

from typing import Any


class RegionPage:
	"""Render region selection state as terminal-friendly lines."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[RegionSelect]"]
		lines.append(f"  mode: {view_model.get('mode')}")
		lines.append(f"  map: {view_model.get('selected_map_display_name') or view_model.get('selected_map_id')}")
		lines.append(f"  region_count: {view_model.get('region_count', 0)}")

		selected_name = view_model.get("selected_region_display_name") or "<none>"
		selected_id = view_model.get("selected_region_id") or "<none>"
		selected_index = view_model.get("selected_region_index")
		if isinstance(selected_index, int):
			lines.append(
				f"  selected: {selected_name} ({selected_id}) [{selected_index + 1}/{view_model.get('region_count', 0)}]"
			)
		else:
			lines.append(f"  selected: {selected_name} ({selected_id})")

		available = view_model.get("available_region_names") or []
		if available:
			lines.append(f"  options: {', '.join(available)}")
		else:
			lines.append("  options: <no available regions>")

		lines.append("  actions: NAV next | CONFIRM preview | NAV_LONG stats | BACK_LONG map")
		return lines

