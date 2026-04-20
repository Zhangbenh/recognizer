"""Single-thread FIFO event queue."""

from __future__ import annotations

from collections import deque
from typing import Optional

from application.events import Event


class EventQueue:
	"""Bounded FIFO queue for state machine events."""

	def __init__(self, max_size: int = 256) -> None:
		if max_size <= 0:
			raise ValueError("max_size must be greater than zero")
		self._queue: deque[Event] = deque()
		self._max_size = max_size

	def enqueue(self, event: Event) -> None:
		if len(self._queue) >= self._max_size:
			raise OverflowError("event queue is full")
		self._queue.append(event)

	def dequeue(self) -> Optional[Event]:
		if not self._queue:
			return None
		return self._queue.popleft()

	def peek(self) -> Optional[Event]:
		if not self._queue:
			return None
		return self._queue[0]

	def clear(self) -> None:
		self._queue.clear()

	def is_empty(self) -> bool:
		return not self._queue

	def __len__(self) -> int:
		return len(self._queue)

