"""Renderer that emits compact state snapshots to logger/console."""

from __future__ import annotations

import json
import logging
from typing import Optional

from application.state_context import StateContext
from application.states import State
from presentation.view_models import build_view_model


class Renderer:
	"""Render only when state/view changes to reduce terminal noise."""

	def __init__(self, *, logger: Optional[logging.Logger] = None) -> None:
		self._logger = logger
		self._last_signature: Optional[str] = None

	def render(self, state: State, ctx: StateContext) -> dict:
		view_model = build_view_model(state, ctx)
		signature = json.dumps(view_model, sort_keys=True, ensure_ascii=True, default=str)
		if signature == self._last_signature:
			return view_model

		self._last_signature = signature
		self._emit(view_model)
		return view_model

	def _emit(self, view_model: dict) -> None:
		lines = ["[Render]"]
		for key in sorted(view_model.keys()):
			lines.append(f"  {key}: {view_model[key]}")
		text = "\n".join(lines)
		if self._logger:
			self._logger.info("\n%s", text)
		else:
			print(text)

