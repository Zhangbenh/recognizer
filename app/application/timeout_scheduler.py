"""Neutral timeout scheduler: only emits TIMEOUT and never business events."""

from __future__ import annotations

from time import monotonic
from typing import Optional

from application.events import Event, EventType
from application.state_context import StateContext
from application.states import State


class TimeoutScheduler:
	"""Track at most one active state timeout in the single-thread runtime."""

	def __init__(self) -> None:
		self._active_state: Optional[State] = None
		self._deadline: Optional[float] = None

	def register(self, state: State, timeout_seconds: float, ctx: Optional[StateContext] = None) -> float:
		deadline = monotonic() + timeout_seconds
		self._active_state = state
		self._deadline = deadline
		self._sync_deadline_field(state, deadline, ctx)
		return deadline

	def clear(self, ctx: Optional[StateContext] = None) -> None:
		if self._active_state is not None:
			self._sync_deadline_field(self._active_state, None, ctx)
		self._active_state = None
		self._deadline = None

	def poll(self, current_state: State, ctx: Optional[StateContext] = None) -> Optional[Event]:
		if self._active_state is None or self._deadline is None:
			return None
		if self._active_state != current_state:
			return None
		if monotonic() < self._deadline:
			return None

		self.clear(ctx)
		return Event(EventType.TIMEOUT, source="TimeoutScheduler")

	def _sync_deadline_field(
		self,
		state: State,
		value: Optional[float],
		ctx: Optional[StateContext],
	) -> None:
		if ctx is None:
			return
		if state == State.INFERENCING:
			ctx.infer_deadline = value
		elif state == State.DISPLAY:
			ctx.display_deadline = value
		elif state == State.RECORDING:
			ctx.record_deadline = value

