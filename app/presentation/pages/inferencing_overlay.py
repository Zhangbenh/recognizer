"""INFERENCING overlay renderer."""

from __future__ import annotations

from typing import Any


class InferencingOverlay:
	"""Render inferencing status overlay."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Inferencing]"]
		lines.append(f"  mode: {view_model.get('mode')}")
		lines.append(f"  status: {view_model.get('status')}")
		lines.append(f"  hint: {view_model.get('hint')}")
		return lines
