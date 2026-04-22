"""BOOTING page renderer."""

from __future__ import annotations

from typing import Any


class BootingPage:
	"""Render boot progress summary."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[启动中]"]
		lines.append(f"  标题: {view_model.get('title')}")
		lines.append(f"  状态: {view_model.get('status')}")
		lines.append(f"  提示: {view_model.get('hint')}")
		return lines
