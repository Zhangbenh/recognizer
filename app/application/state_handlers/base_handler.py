"""Base handler contracts for state enter/exit behaviors."""

from __future__ import annotations

from typing import Optional

from application.events import Event
from application.state_context import StateContext
from application.states import State


class BaseStateHandler:
	"""Base class for state handlers.

	Handlers never mutate current_state directly; they only mutate context and
	may emit follow-up events to be enqueued by the state machine.
	"""

	def __init__(self, state: State) -> None:
		self.state = state

	def on_enter(self, _ctx: StateContext) -> list[Event]:
		return []

	def on_exit(self, _ctx: StateContext) -> None:
		return None


class NoOpStateHandler(BaseStateHandler):
	"""Fallback handler used when a state-specific handler is not registered."""

	def __init__(self, state: State) -> None:
		super().__init__(state=state)

