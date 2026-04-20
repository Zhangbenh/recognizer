"""HOME state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State


class HomeHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.HOME)

	def on_enter(self, ctx: StateContext):
		ctx.clear_flow_transients()
		return []

