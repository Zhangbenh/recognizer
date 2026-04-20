"""PREVIEW state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State


class PreviewHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.PREVIEW)

	def on_enter(self, ctx: StateContext):
		# Keep camera chain alive in adapter layer; here we only reset transient
		# display data that should not leak into next recognition turn.
		ctx.current_stats_snapshot = None
		return []

