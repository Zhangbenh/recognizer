"""RECORDING state handler."""

from __future__ import annotations

from application.events import Event, EventType
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.errors import DataError
from domain.sampling_recorder import SamplingRecorder


class RecordingHandler(BaseStateHandler):
	def __init__(self, *, sampling_recorder: SamplingRecorder) -> None:
		super().__init__(State.RECORDING)
		self._sampling_recorder = sampling_recorder

	def on_enter(self, ctx: StateContext):
		result = ctx.last_recognition_result
		if result is None or not result.is_recognized:
			ctx.set_error(DataError("missing_or_unrecognized_result", retryable=False))
			return [
				Event(
					EventType.RECORD_FAIL,
					source="RecordingHandler",
					payload={"reason": "missing_or_unrecognized_result"},
				)
			]

		if not ctx.selected_region_id:
			ctx.set_error(DataError("missing_region_id", retryable=False))
			return [
				Event(
					EventType.RECORD_FAIL,
					source="RecordingHandler",
					payload={"reason": "missing_region_id"},
				)
			]

		try:
			self._sampling_recorder.record(ctx.selected_region_id, result)
		except Exception as exc:
			ctx.set_error(exc)
			return [
				Event(
					EventType.RECORD_FAIL,
					source="RecordingHandler",
					payload={"reason": str(exc)},
				)
			]

		return [Event(EventType.RECORD_OK, source="RecordingHandler")]

