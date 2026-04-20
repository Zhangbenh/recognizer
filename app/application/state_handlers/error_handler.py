"""ERROR state handler."""

from __future__ import annotations

from typing import Callable

from application.events import Event, EventType
from application.error_policy import ErrorPolicy
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State


class ErrorHandler(BaseStateHandler):
	def __init__(
		self,
		*,
		retry_executor: Callable[[], None] | None = None,
		error_policy: ErrorPolicy | None = None,
	) -> None:
		super().__init__(State.ERROR)
		self._retry_executor = retry_executor
		self._error_policy = error_policy or ErrorPolicy()

	def on_enter(self, ctx: StateContext):
		ctx.error_is_retryable = self._error_policy.is_retryable(ctx.last_error)
		if not ctx.retry_requested:
			return []

		ctx.retry_requested = False
		ctx.retry_success = False

		if not ctx.error_is_retryable:
			return [Event(EventType.RETRY_PRESS, source="ErrorHandler")]

		try:
			if self._retry_executor is None:
				raise RuntimeError("retry executor is not configured")
			self._retry_executor()
		except Exception as exc:
			ctx.set_error(exc)
			ctx.retry_success = False
		else:
			ctx.retry_success = True

		return [Event(EventType.RETRY_PRESS, source="ErrorHandler")]

