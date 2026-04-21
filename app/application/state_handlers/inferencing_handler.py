"""INFERENCING state handler."""

from __future__ import annotations

from application.events import Event, EventType
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.errors import InferenceError
from domain.recognition_service import RecognitionService


class InferencingHandler(BaseStateHandler):
	def __init__(self, *, recognition_service: RecognitionService) -> None:
		super().__init__(State.INFERENCING)
		self._recognition_service = recognition_service

	def on_enter(self, ctx: StateContext):
		if ctx.last_captured_frame is None:
			ctx.set_error(InferenceError("missing captured frame", retryable=False))
			return [
				Event(
					EventType.INFER_FAIL,
					source="InferencingHandler",
					payload={"reason": "missing_captured_frame"},
				)
			]

		try:
			result = self._recognition_service.recognize(ctx.last_captured_frame)
		except Exception as exc:
			ctx.set_error(exc)
			return [
				Event(
					EventType.INFER_FAIL,
					source="InferencingHandler",
					payload={"reason": str(exc)},
				)
			]

		return [
			Event(
				EventType.INFER_OK,
				source="InferencingHandler",
				payload={"recognition_result": result},
			)
		]

