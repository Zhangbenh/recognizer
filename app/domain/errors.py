"""Domain exception hierarchy used by runtime and error policy."""

from __future__ import annotations

from .models import ErrorInfo


class RecognizerError(Exception):
	"""Base error type carrying retryability metadata."""

	def __init__(self, message: str, *, retryable: bool = False) -> None:
		super().__init__(message)
		self.retryable = retryable

	def to_error_info(self) -> ErrorInfo:
		return ErrorInfo(
			error_type=self.__class__.__name__,
			message=str(self),
			retryable=self.retryable,
		)


class ConfigError(RecognizerError):
	pass


class LabelError(RecognizerError):
	pass


class ModelError(RecognizerError):
	pass


class ReleaseGateError(RecognizerError):
	pass


class CameraError(RecognizerError):
	pass


class InferenceError(RecognizerError):
	pass


class StorageError(RecognizerError):
	pass


class DataError(RecognizerError):
	pass


class StateMachineError(RecognizerError):
	pass


class IllegalInternalEventError(StateMachineError):
	pass

