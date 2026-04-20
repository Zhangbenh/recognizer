"""Keyboard input adapter for local development environments."""

from __future__ import annotations

from collections import deque
from typing import Any

from infrastructure.input.base_input_adapter import BaseInputAdapter


class KeyboardAdapter(BaseInputAdapter):
	"""Non-blocking keyboard adapter.

	Default key mapping (Windows terminal):
	- c -> BTN1_SHORT
	- C -> BTN1_LONG
	- v -> BTN2_SHORT
	- V -> BTN2_LONG
	"""

	_KEY_MAP = {
		"c": "BTN1_SHORT",
		"C": "BTN1_LONG",
		"v": "BTN2_SHORT",
		"V": "BTN2_LONG",
	}

	def __init__(self, *, enable_stdin_poll: bool = True) -> None:
		self._enable_stdin_poll = enable_stdin_poll
		self._queued_events: deque[str] = deque()

	def push_simulated_event(self, event_type: str) -> None:
		self._queued_events.append(event_type)

	def poll_raw_inputs(self) -> list[Any]:
		events: list[dict[str, Any]] = []

		while self._queued_events:
			queued = self._queued_events.popleft()
			events.append({"event_type": queued, "source": "KeyboardAdapter.queue"})

		if self._enable_stdin_poll:
			events.extend(self._poll_stdin_non_blocking())

		return events

	def close(self) -> None:
		self._queued_events.clear()

	def _poll_stdin_non_blocking(self) -> list[dict[str, Any]]:
		try:
			import msvcrt
		except ImportError:
			return []

		events: list[dict[str, Any]] = []
		while msvcrt.kbhit():
			char = msvcrt.getwch()
			mapped = self._KEY_MAP.get(char)
			if not mapped:
				continue
			events.append({"event_type": mapped, "source": "KeyboardAdapter.stdin"})
		return events

