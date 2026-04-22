"""REGION_SELECT page renderer."""

from __future__ import annotations

from typing import Any


class RegionPage:
	"""Render region selection state as terminal-friendly lines."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[区域选择]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append(f"  地图: {view_model.get('selected_map_display_name') or view_model.get('selected_map_id')}")
		lines.append(f"  区域数量: {view_model.get('region_count', 0)}")

		selected_name = view_model.get("selected_region_display_name") or "<未选择>"
		selected_id = view_model.get("selected_region_id") or "<未选择>"
		selected_index = view_model.get("selected_region_index")
		if isinstance(selected_index, int):
			lines.append(
				f"  当前区域: {selected_name} ({selected_id}) [{selected_index + 1}/{view_model.get('region_count', 0)}]"
			)
		else:
			lines.append(f"  当前区域: {selected_name} ({selected_id})")

		available = view_model.get("available_region_names") or []
		if available:
			lines.append(f"  可选区域: {', '.join(available)}")
		else:
			lines.append("  可选区域: <无可用区域>")

		lines.append(f"  操作: {view_model.get('hint')}")
		return lines

