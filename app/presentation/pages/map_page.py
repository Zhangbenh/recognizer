"""MAP_SELECT page renderer."""

from __future__ import annotations

from typing import Any


class MapPage:
	"""Render map selection state as terminal-friendly lines."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[MapSelect]"]
		lines.append(f"  mode: {view_model.get('mode')}")
		lines.append(f"  map_count: {view_model.get('map_count', 0)}")

		selected_name = view_model.get("selected_map_display_name") or "<none>"
		selected_id = view_model.get("selected_map_id") or "<none>"
		selected_index = view_model.get("selected_map_index")
		if isinstance(selected_index, int):
			lines.append(f"  selected: {selected_name} ({selected_id}) [{selected_index + 1}/{view_model.get('map_count', 0)}]")
		else:
			lines.append(f"  selected: {selected_name} ({selected_id})")

		available = view_model.get("available_map_names") or []
		if available:
			lines.append(f"  options: {', '.join(available)}")
		else:
			lines.append("  options: <no available maps>")

		lines.append("  actions: NAV next | CONFIRM select | BACK_LONG home")
		return lines

