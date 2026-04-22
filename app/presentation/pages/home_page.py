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

		lines = ["[首页]"]
		lines.append(f"  {normal_flag} 普通识别")
		lines.append(f"  {sampling_flag} 采样统计")
		lines.append(f"  当前选项: {view_model.get('selected_home_option_display_name')}")
		lines.append(f"  提示: {view_model.get('hint')}")
		return lines
