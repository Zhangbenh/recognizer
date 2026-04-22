"""DISPLAY/RECORDING page renderer."""

from __future__ import annotations

from typing import Any


class DisplayPage:
	"""Render display result and recording light hint."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[识别结果]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append(f"  已识别: {'是' if view_model.get('is_recognized') else '否'}")
		lines.append(f"  显示名称: {view_model.get('display_name')}")
		lines.append(f"  植物名称: {view_model.get('plant_name')}")

		confidence = view_model.get("confidence")
		if isinstance(confidence, float):
			lines.append(f"  置信度: {confidence:.4f}")
		else:
			lines.append(f"  置信度: {confidence}")

		lines.append(f"  提示: {view_model.get('hint')}")

		return lines

	@staticmethod
	def render_recording(view_model: dict[str, Any]) -> list[str]:
		lines = ["[记录中]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")
		lines.append("  状态: 正在写入统计...")
		lines.append(f"  区域: {view_model.get('selected_region_id')}")
		lines.append(f"  显示名称: {view_model.get('display_name')}")
		return lines

