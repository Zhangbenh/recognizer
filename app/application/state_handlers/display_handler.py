"""DISPLAY state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State


class DisplayHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.DISPLAY)

	def on_enter(self, _ctx: StateContext):
		return []

