"""Event definitions for input, internal flow, timeout, and system errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any, Optional


class EventType(str, Enum):
	# External events.
	CONFIRM_PRESS = "CONFIRM_PRESS"
	NAV_PRESS = "NAV_PRESS"
	BACK_LONG_PRESS = "BACK_LONG_PRESS"
	NAV_LONG_PRESS = "NAV_LONG_PRESS"
	RETRY_PRESS = "RETRY_PRESS"

	# Internal flow events.
	BOOT_OK = "BOOT_OK"
	BOOT_FAIL = "BOOT_FAIL"
	CAPTURE_OK = "CAPTURE_OK"
	CAPTURE_FAIL = "CAPTURE_FAIL"
	INFER_OK = "INFER_OK"
	INFER_FAIL = "INFER_FAIL"
	RECORD_OK = "RECORD_OK"
	RECORD_FAIL = "RECORD_FAIL"

	# Neutral/system events.
	TIMEOUT = "TIMEOUT"
	SYSTEM_ERROR = "SYSTEM_ERROR"


EXTERNAL_EVENTS: set[EventType] = {
	EventType.CONFIRM_PRESS,
	EventType.NAV_PRESS,
	EventType.BACK_LONG_PRESS,
	EventType.NAV_LONG_PRESS,
	EventType.RETRY_PRESS,
}

INTERNAL_EVENTS: set[EventType] = {
	EventType.BOOT_OK,
	EventType.BOOT_FAIL,
	EventType.CAPTURE_OK,
	EventType.CAPTURE_FAIL,
	EventType.INFER_OK,
	EventType.INFER_FAIL,
	EventType.RECORD_OK,
	EventType.RECORD_FAIL,
}


@dataclass(slots=True)
class Event:
	event_type: EventType
	payload: dict[str, Any] = field(default_factory=dict)
	source: Optional[str] = None
	created_at: float = field(default_factory=monotonic)

	@classmethod
	def system_error(
		cls,
		message: str,
		*,
		source: Optional[str] = None,
		details: Optional[dict[str, Any]] = None,
	) -> "Event":
		payload = {"message": message}
		if details:
			payload["details"] = details
		return cls(EventType.SYSTEM_ERROR, payload=payload, source=source)

