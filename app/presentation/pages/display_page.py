"""DISPLAY/RECORDING page renderer."""

from __future__ import annotations

from typing import Any


class DisplayPage:
	"""Render display result and recording light hint."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Display]"]
		lines.append(f"  mode: {view_model.get('mode')}")
		lines.append(f"  recognized: {view_model.get('is_recognized')}")
		lines.append(f"  display_name: {view_model.get('display_name')}")
		lines.append(f"  plant_name: {view_model.get('plant_name')}")

		confidence = view_model.get("confidence")
		if isinstance(confidence, float):
			lines.append(f"  confidence: {confidence:.4f}")
		else:
			lines.append(f"  confidence: {confidence}")

		return lines

	@staticmethod
	def render_recording(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Recording]"]
		lines.append(f"  mode: {view_model.get('mode')}")
		lines.append("  status: recording stats...")
		lines.append(f"  region_id: {view_model.get('selected_region_id')}")
		lines.append(f"  display_name: {view_model.get('display_name')}")
		return lines

