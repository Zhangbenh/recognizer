"""ERROR page renderer."""

from __future__ import annotations

from typing import Any


class ErrorPage:
	"""Render error details and recovery hints."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[错误]"]
		lines.append(f"  错误类型: {view_model.get('error_type')}")
		lines.append(f"  错误信息: {view_model.get('error_message')}")

		retryable = bool(view_model.get("retryable"))
		lines.append(f"  可重试: {'是' if retryable else '否'}")

		if retryable:
			lines.append("  操作: CONFIRM 重试")
		else:
			lines.append("  操作: CONFIRM 忽略（不可重试）")

		return lines

