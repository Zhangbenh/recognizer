"""ERROR page renderer."""

from __future__ import annotations

from typing import Any


class ErrorPage:
	"""Render error details and recovery hints."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Error]"]
		lines.append(f"  error_type: {view_model.get('error_type')}")
		lines.append(f"  message: {view_model.get('error_message')}")

		retryable = bool(view_model.get("retryable"))
		lines.append(f"  retryable: {retryable}")

		if retryable:
			lines.append("  actions: CONFIRM retry")
		else:
			lines.append("  actions: CONFIRM ignored (non-retryable)")

		return lines

