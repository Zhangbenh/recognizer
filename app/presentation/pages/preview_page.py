"""PREVIEW page renderer."""

from __future__ import annotations

from typing import Any


class PreviewPage:
	"""Render preview state information and shortcuts."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[预览]"]
		lines.append(f"  模式: {view_model.get('mode_display_name')}")

		if view_model.get("mode") == "sampling":
			lines.append(
				"  目标: %s / %s"
				% (
					view_model.get("selected_map_display_name") or view_model.get("selected_map_id"),
					view_model.get("selected_region_display_name") or view_model.get("selected_region_id"),
				)
			)

		last_result_name = view_model.get("last_recognition_display_name")
		last_result_source = view_model.get("last_recognition_source_display_name")
		if last_result_source:
			lines.append(f"  上次结果: {last_result_name or '未识别'}")
			lines.append(f"  识别来源: {last_result_source}")

		error_type = view_model.get("non_fatal_error_type")
		error_message = view_model.get("non_fatal_error_message")
		if error_message:
			lines.append(f"  非致命错误类型: {error_type}")
			lines.append(f"  非致命错误信息: {error_message}")
			lines.append(f"  警告: {error_type}: {error_message}")

		lines.append("  叠加层: 中心十字线")
		lines.append(f"  提示: {view_model.get('hint')}")
		return lines
