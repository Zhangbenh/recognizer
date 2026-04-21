"""HOME page renderer."""

from __future__ import annotations

from typing import Any


class HomePage:
	"""Render mode selection page."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		selected = str(view_model.get("selected_home_option") or "normal")
		normal_flag = ">" if selected == "normal" else " "
		sampling_flag = ">" if selected == "sampling" else " "

		lines = ["[Home]"]
		lines.append(f"  {normal_flag} normal")
		lines.append(f"  {sampling_flag} sampling")
		lines.append(f"  hint: {view_model.get('hint')}")
		return lines
