"""ERROR state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State


class ErrorHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.ERROR)

	def on_enter(self, ctx: StateContext):
		ctx.error_is_retryable = bool(ctx.last_error and ctx.last_error.retryable)
		return []

