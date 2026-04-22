"""State definitions for the runtime state machine."""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
	BOOTING = "BOOTING"
	HOME = "HOME"
	MAP_SELECT = "MAP_SELECT"
	MAP_STATS = "MAP_STATS"
	REGION_SELECT = "REGION_SELECT"
	PREVIEW = "PREVIEW"
	CAPTURED = "CAPTURED"
	INFERENCING = "INFERENCING"
	DISPLAY = "DISPLAY"
	RECORDING = "RECORDING"
	STATS = "STATS"
	ERROR = "ERROR"


ALL_STATES: tuple[State, ...] = tuple(State)

