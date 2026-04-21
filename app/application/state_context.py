"""Runtime context carried by the state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from domain.constants import HOME_OPTION_NORMAL, HOME_OPTION_SAMPLING, MODE_NORMAL
from domain.errors import RecognizerError
from domain.models import ErrorInfo, RecognitionResult, StatsSnapshot


@dataclass(slots=True)
class StateContext:
	"""Minimal required runtime fields defined by the state-machine design."""

	mode: str = MODE_NORMAL
	selected_home_option: str = HOME_OPTION_NORMAL
	selected_map_id: Optional[str] = None
	selected_map_index: Optional[int] = None
	selected_region_id: Optional[str] = None
	selected_region_index: Optional[int] = None
	selected_stats_page_index: int = 0
	last_captured_frame: Any = None
	last_recognition_result: Optional[RecognitionResult] = None
	last_error: Optional[ErrorInfo] = None
	error_is_retryable: bool = False
	display_deadline: Optional[float] = None
	infer_deadline: Optional[float] = None
	record_deadline: Optional[float] = None
	current_stats_snapshot: Optional[StatsSnapshot] = None

	# Operational fields used by guards and navigation actions.
	available_maps: list[dict[str, Any]] = field(default_factory=list)
	available_regions: list[dict[str, Any]] = field(default_factory=list)
	retry_success: bool = False
	retry_requested: bool = False
	home_option_dirty: bool = False
	preview_error_flash_pending: bool = False

	def toggle_home_option(self) -> None:
		if self.selected_home_option == HOME_OPTION_NORMAL:
			self.selected_home_option = HOME_OPTION_SAMPLING
		else:
			self.selected_home_option = HOME_OPTION_NORMAL

	def clear_flow_transients(self) -> None:
		self.last_captured_frame = None
		self.last_recognition_result = None
		self.display_deadline = None
		self.infer_deadline = None
		self.record_deadline = None

	def set_error(self, error: ErrorInfo | RecognizerError | Exception) -> None:
		if isinstance(error, ErrorInfo):
			self.last_error = error
		elif isinstance(error, RecognizerError):
			self.last_error = error.to_error_info()
		else:
			self.last_error = ErrorInfo(
				error_type=error.__class__.__name__,
				message=str(error),
				retryable=False,
			)
		self.error_is_retryable = self.last_error.retryable

	def clear_error(self) -> None:
		self.last_error = None
		self.error_is_retryable = False
		self.retry_success = False
		self.retry_requested = False
		self.preview_error_flash_pending = False

	@property
	def has_available_maps(self) -> bool:
		return len(self.available_maps) > 0

	@property
	def has_available_regions(self) -> bool:
		return len(self.available_regions) > 0

	@property
	def has_recognition(self) -> bool:
		return self.last_recognition_result is not None

	@property
	def is_recognized(self) -> bool:
		return bool(self.last_recognition_result and self.last_recognition_result.is_recognized)

