"""CAPTURED state handler."""

from __future__ import annotations

from application.events import Event, EventType
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.errors import CameraError


class CapturedHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.CAPTURED)

	def on_enter(self, ctx: StateContext):
		if ctx.last_captured_frame is None:
			ctx.set_error(CameraError("missing captured frame", retryable=False))
			return [
				Event(
					EventType.CAPTURE_FAIL,
					source="CapturedHandler",
					payload={"reason": "missing_captured_frame"},
				)
			]
		return [Event(EventType.CAPTURE_OK, source="CapturedHandler")]

