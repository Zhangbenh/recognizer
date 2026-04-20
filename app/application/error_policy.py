"""Centralized error recovery policy used by state handlers/state machine."""

from __future__ import annotations

from typing import Optional

from application.states import State
from domain.errors import (
	CameraError,
	ConfigError,
	DataError,
	InferenceError,
	LabelError,
	ModelError,
	RecognizerError,
	StateMachineError,
	StorageError,
)
from domain.models import ErrorInfo


class ErrorPolicy:
	"""Map errors to recovery targets.

	Returning None means "stay in current state and render degraded UI".
	"""

	def is_retryable(self, error: ErrorInfo | Exception | None) -> bool:
		if error is None:
			return False
		if isinstance(error, ErrorInfo):
			return error.retryable
		if isinstance(error, RecognizerError):
			return error.retryable
		return False

	def recovery_target(self, current_state: State, error: ErrorInfo | Exception) -> Optional[State]:
		error_type = self._error_type_name(error)

		if error_type == DataError.__name__ and current_state == State.STATS:
			return None

		if error_type in {
			ConfigError.__name__,
			LabelError.__name__,
			ModelError.__name__,
			StateMachineError.__name__,
		}:
			return State.ERROR

		if error_type in {
			CameraError.__name__,
			InferenceError.__name__,
			StorageError.__name__,
		}:
			if current_state in {State.BOOTING, State.ERROR}:
				return State.ERROR
			if current_state in {
				State.PREVIEW,
				State.CAPTURED,
				State.INFERENCING,
				State.DISPLAY,
				State.RECORDING,
			}:
				return State.PREVIEW
			return State.HOME

		return State.ERROR

	def _error_type_name(self, error: ErrorInfo | Exception) -> str:
		if isinstance(error, ErrorInfo):
			return error.error_type
		return error.__class__.__name__

