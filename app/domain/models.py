"""Domain models used by the runtime state machine and services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now_iso() -> str:
	"""Return an ISO timestamp in UTC."""

	return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ErrorInfo:
	"""Structured error payload shared across runtime layers."""

	error_type: str
	message: str
	retryable: bool = False
	details: dict[str, Any] = field(default_factory=dict)
	created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class RecognitionResult:
	"""Normalized recognition output consumed by state handlers and UI."""

	class_id: Optional[int]
	plant_key: Optional[str]
	plant_name: Optional[str]
	display_name: Optional[str]
	confidence: float
	is_recognized: bool
	top3: list[tuple[int, float]] = field(default_factory=list)
	recognized_at: str = field(default_factory=utc_now_iso)

	@classmethod
	def unrecognized(cls, confidence: float = 0.0) -> "RecognitionResult":
		return cls(
			class_id=None,
			plant_key=None,
			plant_name=None,
			display_name=None,
			confidence=confidence,
			is_recognized=False,
			top3=[],
		)


@dataclass(slots=True)
class StatsItem:
	"""Statistics item for one plant inside a region snapshot."""

	plant_key: str
	plant_name: str
	display_name: str
	count: int
	last_confidence: float
	last_seen_at: str


@dataclass(slots=True)
class StatsSnapshot:
	"""Read-only statistics snapshot prepared for STATS rendering."""

	region_id: str
	items: list[StatsItem] = field(default_factory=list)
	page_size: int = 4

	@property
	def total_pages(self) -> int:
		if not self.items:
			return 1
		return (len(self.items) + self.page_size - 1) // self.page_size

	def page(self, index: int) -> list[StatsItem]:
		if index < 0:
			index = 0
		start = index * self.page_size
		end = start + self.page_size
		return self.items[start:end]

