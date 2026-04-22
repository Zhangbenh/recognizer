"""MAP_SELECT page renderer."""

from __future__ import annotations

from typing import Any


class MapPage:
	"""Render map selection state as terminal-friendly lines."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[地图选择]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append(f"  地图数量: {view_model.get('map_count', 0)}")

		selected_name = view_model.get("selected_map_display_name") or "<未选择>"
		selected_id = view_model.get("selected_map_id") or "<未选择>"
		selected_index = view_model.get("selected_map_index")
		if isinstance(selected_index, int):
			lines.append(f"  当前地图: {selected_name} ({selected_id}) [{selected_index + 1}/{view_model.get('map_count', 0)}]")
		else:
			lines.append(f"  当前地图: {selected_name} ({selected_id})")

		available = view_model.get("available_map_names") or []
		if available:
			lines.append(f"  可选地图: {', '.join(available)}")
		else:
			lines.append("  可选地图: <无可用地图>")

		lines.append(f"  操作: {view_model.get('hint')}")
		return lines

