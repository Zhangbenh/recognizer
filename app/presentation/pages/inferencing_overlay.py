"""INFERENCING overlay renderer."""

from __future__ import annotations

from typing import Any


class InferencingOverlay:
	"""Render inferencing status overlay."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[识别中]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append(f"  状态: {view_model.get('status')}")
		lines.append(f"  提示: {view_model.get('hint')}")
		return lines
