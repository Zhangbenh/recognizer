"""Application controller that orchestrates loop, input, state machine, and rendering."""

from __future__ import annotations

import logging
import time
from typing import Optional

from application.events import Event, EventType
from application.input_mapper import InputMapper
from application.state_machine import StateMachine
from application.states import State
from domain.recognition_service import RecognitionService
from domain.release_gate_service import ReleaseGateService
from presentation.renderer import Renderer


class AppController:
	"""Runtime composition root for the single-thread loop."""

	def __init__(
		self,
		*,
		state_machine: StateMachine,
		input_adapter,
		input_mapper: InputMapper,
		renderer: Renderer,
		recognition_service: RecognitionService,
		release_gate_service: ReleaseGateService,
		logger: Optional[logging.Logger] = None,
		max_events_per_tick: int = 64,
	) -> None:
		self._state_machine = state_machine
		self._input_adapter = input_adapter
		self._input_mapper = input_mapper
		self._renderer = renderer
		self._recognition_service = recognition_service
		self._release_gate_service = release_gate_service
		self._logger = logger or logging.getLogger("recognizer.controller")
		self._max_events_per_tick = max(1, int(max_events_per_tick))
		self._running = False

	def run(self, *, max_ticks: Optional[int] = None, idle_sleep_s: float = 0.02) -> None:
		tick_count = 0
		self._running = True
		self._state_machine.start()

		try:
			while self._running:
				did_work = self.tick()
				tick_count += 1

				if max_ticks is not None and tick_count >= max_ticks:
					break

				if not did_work and idle_sleep_s > 0:
					time.sleep(idle_sleep_s)
		except KeyboardInterrupt:
			self._logger.info("runtime interrupted by user")
		finally:
			self.stop()

	def tick(self) -> bool:
		did_work = False
		current_state = self._state_machine.current_state

		for raw_input in self._poll_raw_inputs_safe():
			event = self._input_mapper.map_raw_input(raw_input, current_state)
			if event is None:
				continue

			self._prepare_event_before_enqueue(event, current_state)
			self._state_machine.enqueue(event)
			did_work = True

		processed = 0
		while processed < self._max_events_per_tick and self._state_machine.process_next_event():
			processed += 1
			did_work = True

		if processed >= self._max_events_per_tick:
			self._logger.warning("max events per tick reached: %s", self._max_events_per_tick)

		self._renderer.render(self._state_machine.current_state, self._state_machine.context)
		return did_work

	def request_stop(self) -> None:
		self._running = False

	def stop(self) -> None:
		self._running = False

		try:
			self._input_adapter.close()
		except Exception:
			self._logger.exception("failed to close input adapter")

		try:
			self._recognition_service.shutdown()
		except Exception:
			self._logger.exception("failed to shutdown recognition service")

	def _poll_raw_inputs_safe(self):
		try:
			return self._input_adapter.poll_raw_inputs()
		except Exception as exc:
			self._state_machine.context.set_error(exc)
			self._state_machine.enqueue(
				Event.system_error(
					message="input_poll_failed",
					source="AppController",
					details={"reason": str(exc)},
				)
			)
			return []

	def _prepare_event_before_enqueue(self, event: Event, current_state: State) -> None:
		if current_state == State.PREVIEW and event.event_type == EventType.CONFIRM_PRESS:
			self._attach_capture_frame(event)
		elif current_state == State.ERROR and event.event_type == EventType.RETRY_PRESS:
			self._attempt_retry_boot()

	def _attach_capture_frame(self, event: Event) -> None:
		try:
			frame = self._recognition_service.capture_frame()
		except Exception as exc:
			event.payload["capture_error"] = str(exc)
			self._state_machine.context.set_error(exc)
			return

		event.payload["frame"] = frame

	def _attempt_retry_boot(self) -> None:
		ctx = self._state_machine.context
		try:
			self._release_gate_service.ensure_pass()
			self._recognition_service.boot()
		except Exception as exc:
			ctx.retry_success = False
			ctx.set_error(exc)
			return

		ctx.retry_success = True

