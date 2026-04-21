"""BOOTING page renderer."""

from __future__ import annotations

from typing import Any


class BootingPage:
	"""Render boot progress summary."""

	@staticmethod
	def render(view_model: dict[str, Any]) -> list[str]:
		lines = ["[Booting]"]
		lines.append(f"  title: {view_model.get('title')}")
		lines.append(f"  status: {view_model.get('status')}")
		lines.append("  hint: initializing camera and model...")
		return lines
