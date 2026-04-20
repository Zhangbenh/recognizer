"""Map raw input events into normalized state-machine events."""

from __future__ import annotations

from typing import Any, Optional

from application.events import Event, EventType
from application.states import State


class InputMapper:
	"""Convert adapter-level raw input into state-machine events."""

	_RAW_NAME_TO_EVENT: dict[str, EventType] = {
		"BTN1_SHORT": EventType.CONFIRM_PRESS,
		"BTN1_LONG": EventType.NAV_LONG_PRESS,
		"BTN2_SHORT": EventType.NAV_PRESS,
		"BTN2_LONG": EventType.BACK_LONG_PRESS,
		"CONFIRM_PRESS": EventType.CONFIRM_PRESS,
		"NAV_PRESS": EventType.NAV_PRESS,
		"BACK_LONG_PRESS": EventType.BACK_LONG_PRESS,
		"NAV_LONG_PRESS": EventType.NAV_LONG_PRESS,
		"RETRY_PRESS": EventType.RETRY_PRESS,
	}

	def map_raw_input(self, raw_input: Any, current_state: State) -> Optional[Event]:
		raw_name = self._extract_name(raw_input)
		if raw_name is None:
			return None

		mapped = self._RAW_NAME_TO_EVENT.get(raw_name)
		if mapped is None:
			return None

		# RETRY_PRESS must come from ERROR confirm mapping.
		if current_state == State.ERROR and mapped == EventType.CONFIRM_PRESS:
			return Event(
				EventType.RETRY_PRESS,
				source="ErrorPageInputMapping",
				payload={"raw_event": raw_name},
			)

		return Event(mapped, source="InputAdapter", payload={"raw_event": raw_name})

	def _extract_name(self, raw_input: Any) -> Optional[str]:
		if isinstance(raw_input, EventType):
			return raw_input.value

		if isinstance(raw_input, str):
			return raw_input

		if isinstance(raw_input, dict):
			for key in ("event_type", "event", "name"):
				value = raw_input.get(key)
				if isinstance(value, EventType):
					return value.value
				if isinstance(value, str):
					return value

			button = raw_input.get("button")
			press_type = raw_input.get("press_type")
			if isinstance(button, str) and isinstance(press_type, str):
				candidate = f"{button}_{press_type}"
				if candidate in self._RAW_NAME_TO_EVENT:
					return candidate

		return None

