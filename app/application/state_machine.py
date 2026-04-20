"""Single-thread event-driven state machine runtime."""

from __future__ import annotations

from typing import Optional

from application.event_queue import EventQueue
from application.events import Event, EventType
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler, NoOpStateHandler
from application.states import State
from application.timeout_scheduler import TimeoutScheduler
from application.transition_engine import TransitionEngine
from domain.constants import DISPLAY_TIMEOUT_SECONDS, INFER_TIMEOUT_SECONDS, RECORD_TIMEOUT_SECONDS


class StateMachine:
	"""The only legal flow-control center in runtime."""

	def __init__(
		self,
		*,
		initial_state: State = State.BOOTING,
		context: Optional[StateContext] = None,
		event_queue: Optional[EventQueue] = None,
		transition_engine: Optional[TransitionEngine] = None,
		timeout_scheduler: Optional[TimeoutScheduler] = None,
		handlers: Optional[dict[State, BaseStateHandler]] = None,
	) -> None:
		self._context = context or StateContext()
		self._event_queue = event_queue or EventQueue()
		self._transition_engine = transition_engine or TransitionEngine()
		self._timeout_scheduler = timeout_scheduler or TimeoutScheduler()
		self._current_state = initial_state
		self._started = False

		self._handlers: dict[State, BaseStateHandler] = {
			state: NoOpStateHandler(state) for state in State
		}
		if handlers:
			self._handlers.update(handlers)

	@property
	def current_state(self) -> State:
		return self._current_state

	@property
	def context(self) -> StateContext:
		return self._context

	def start(self) -> None:
		if self._started:
			return
		self._started = True

		self._register_state_timeout(self._current_state)
		enter_events = self._handler(self._current_state).on_enter(self._context)
		self._enqueue_many(enter_events)

	def enqueue(self, event: Event) -> None:
		self._event_queue.enqueue(event)

	def run_once(self) -> bool:
		if not self._started:
			self.start()
		return self.process_next_event()

	def process_next_event(self) -> bool:
		if not self._started:
			self.start()

		timeout_event = self._timeout_scheduler.poll(self._current_state, self._context)
		if timeout_event:
			self.enqueue(timeout_event)

		event = self._event_queue.dequeue()
		if event is None:
			return False

		plan = self._transition_engine.plan_transition(self._current_state, event, self._context)

		# Step 1: validate_event; Step 2: evaluate_guard
		if not plan.is_valid:
			if plan.invalid_internal:
				self._enqueue_system_error(
					message="illegal_internal_event",
					details={
						"state": self._current_state.value,
						"event": event.event_type.value,
					},
				)
			return True

		if not plan.guard_passed:
			return True

		previous_state = self._current_state

		# Step 3: on_exit
		self._handler(previous_state).on_exit(self._context)

		# Step 4: execute_transition_action
		plan.action(self._context, event)

		# Step 5: update_state
		self._current_state = plan.next_state or previous_state

		# State changed: clear previous timeout and register new one if supported.
		self._timeout_scheduler.clear(self._context)
		self._register_state_timeout(self._current_state)

		# Step 6: on_enter
		enter_events = self._handler(self._current_state).on_enter(self._context)

		# Step 7: enqueue_internal_event_if_needed
		self._enqueue_many(plan.follow_up_events)
		self._enqueue_many(enter_events)

		return True

	def _handler(self, state: State) -> BaseStateHandler:
		return self._handlers[state]

	def _register_state_timeout(self, state: State) -> None:
		if state == State.INFERENCING:
			self._timeout_scheduler.register(state, INFER_TIMEOUT_SECONDS, self._context)
		elif state == State.DISPLAY:
			self._timeout_scheduler.register(state, DISPLAY_TIMEOUT_SECONDS, self._context)
		elif state == State.RECORDING:
			self._timeout_scheduler.register(state, RECORD_TIMEOUT_SECONDS, self._context)

	def _enqueue_many(self, events: list[Event]) -> None:
		for event in events:
			self.enqueue(event)

	def _enqueue_system_error(self, message: str, details: Optional[dict[str, str]] = None) -> None:
		self.enqueue(
			Event.system_error(
				message=message,
				source="StateMachine",
				details=details,
			)
		)

