"""PREVIEW page renderer."""

from __future__ import annotations

from typing import Any


class PreviewPage:
	"""Render preview state information and shortcuts."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Preview]"]
		lines.append(f"  mode: {view_model.get('mode')}")

		if view_model.get("mode") == "sampling":
			lines.append(
				"  target: %s / %s"
				% (
					view_model.get("selected_map_display_name") or view_model.get("selected_map_id"),
					view_model.get("selected_region_display_name") or view_model.get("selected_region_id"),
				)
			)

		error_type = view_model.get("non_fatal_error_type")
		error_message = view_model.get("non_fatal_error_message")
		if error_message:
			lines.append(f"  non_fatal_error_type: {error_type}")
			lines.append(f"  non_fatal_error_message: {error_message}")
			lines.append(f"  warning: {error_type}: {error_message}")

		lines.append("  overlay: center crosshair")
		lines.append(f"  hint: {view_model.get('hint')}")
		return lines
