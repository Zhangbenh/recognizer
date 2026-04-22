"""Transition planning for state-machine events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from application.events import EXTERNAL_EVENTS, Event, EventType
from application.guard_evaluator import GuardEvaluator
from application.state_context import StateContext
from application.states import State
from domain.constants import MODE_NORMAL, MODE_SAMPLING
from domain.errors import InferenceError, StorageError
from domain.models import ErrorInfo, RecognitionResult


def _noop_action(_ctx: StateContext, _event: Event) -> None:
	return None


class ValidationResult(str, Enum):
	ALLOWED = "ALLOWED"
	ILLEGAL_EXTERNAL = "ILLEGAL_EXTERNAL"
	ILLEGAL_INTERNAL = "ILLEGAL_INTERNAL"


@dataclass(slots=True)
class TransitionRule:
	next_state: State
	guard: Optional[Callable[[StateContext], bool]] = None
	action: Optional[Callable[[StateContext, Event], None]] = None
	follow_up_builder: Optional[Callable[[StateContext, Event], list[Event]]] = None


@dataclass(slots=True)
class TransitionPlan:
	validation: ValidationResult
	guard_passed: bool = False
	next_state: Optional[State] = None
	action: Callable[[StateContext, Event], None] = _noop_action
	follow_up_events: list[Event] = field(default_factory=list)

	@property
	def is_valid(self) -> bool:
		return self.validation == ValidationResult.ALLOWED

	@property
	def invalid_internal(self) -> bool:
		return self.validation == ValidationResult.ILLEGAL_INTERNAL


class TransitionEngine:
	"""Translate (state, event, context) into an executable transition plan."""

	def __init__(self, guard_evaluator: Optional[GuardEvaluator] = None) -> None:
		self.guards = guard_evaluator or GuardEvaluator()
		self._rules = self._build_rules()

	def validate_event(self, state: State, event_type: EventType) -> ValidationResult:
		rules_for_state = self._rules.get(state, {})
		if event_type in rules_for_state:
			return ValidationResult.ALLOWED
		if event_type in EXTERNAL_EVENTS:
			return ValidationResult.ILLEGAL_EXTERNAL
		return ValidationResult.ILLEGAL_INTERNAL

	def plan_transition(self, state: State, event: Event, ctx: StateContext) -> TransitionPlan:
		validation = self.validate_event(state, event.event_type)
		if validation != ValidationResult.ALLOWED:
			return TransitionPlan(validation=validation)

		candidates = self._rules[state][event.event_type]
		for rule in candidates:
			if rule.guard is None or rule.guard(ctx):
				follow_ups = rule.follow_up_builder(ctx, event) if rule.follow_up_builder else []
				return TransitionPlan(
					validation=ValidationResult.ALLOWED,
					guard_passed=True,
					next_state=rule.next_state,
					action=rule.action or _noop_action,
					follow_up_events=follow_ups,
				)

		# Guard failed: legal event, but no branch selected.
		return TransitionPlan(
			validation=ValidationResult.ALLOWED,
			guard_passed=False,
			next_state=state,
			action=_noop_action,
			follow_up_events=[],
		)

	def _build_rules(self) -> dict[State, dict[EventType, list[TransitionRule]]]:
		rules: dict[State, dict[EventType, list[TransitionRule]]] = {state: {} for state in State}

		def add(state: State, event_type: EventType, rule: TransitionRule) -> None:
			rules[state].setdefault(event_type, []).append(rule)

		# BOOTING
		add(State.BOOTING, EventType.BOOT_OK, TransitionRule(next_state=State.HOME, action=self._action_clear_error))
		add(State.BOOTING, EventType.BOOT_FAIL, TransitionRule(next_state=State.ERROR, action=self._action_update_retryable_from_error))

		# HOME
		add(State.HOME, EventType.NAV_PRESS, TransitionRule(next_state=State.HOME, action=self._action_toggle_home_option))
		add(
			State.HOME,
			EventType.CONFIRM_PRESS,
			TransitionRule(
				next_state=State.PREVIEW,
				guard=self.guards.is_home_normal_selected,
				action=self._action_set_mode_normal,
			),
		)
		add(
			State.HOME,
			EventType.CONFIRM_PRESS,
			TransitionRule(
				next_state=State.MAP_SELECT,
				guard=self.guards.is_home_sampling_selected,
				action=self._action_set_mode_sampling,
			),
		)

		# MAP_SELECT
		add(
			State.MAP_SELECT,
			EventType.NAV_PRESS,
			TransitionRule(
				next_state=State.MAP_SELECT,
				guard=self.guards.has_available_maps,
				action=self._action_map_next,
			),
		)
		add(State.MAP_SELECT, EventType.NAV_PRESS, TransitionRule(next_state=State.MAP_SELECT))
		add(
			State.MAP_SELECT,
			EventType.CONFIRM_PRESS,
			TransitionRule(next_state=State.REGION_SELECT, guard=self.guards.has_available_maps),
		)
		add(State.MAP_SELECT, EventType.CONFIRM_PRESS, TransitionRule(next_state=State.MAP_SELECT))
		add(
			State.MAP_SELECT,
			EventType.NAV_LONG_PRESS,
			TransitionRule(
				next_state=State.MAP_STATS,
				guard=self.guards.has_available_maps,
				action=self._action_map_stats_page_reset,
			),
		)
		add(State.MAP_SELECT, EventType.NAV_LONG_PRESS, TransitionRule(next_state=State.MAP_SELECT))
		add(State.MAP_SELECT, EventType.BACK_LONG_PRESS, TransitionRule(next_state=State.HOME))

		# MAP_STATS
		add(
			State.MAP_STATS,
			EventType.NAV_PRESS,
			TransitionRule(
				next_state=State.MAP_STATS,
				guard=self._has_multiple_map_stats_pages,
				action=self._action_map_stats_page_next,
			),
		)
		add(State.MAP_STATS, EventType.NAV_PRESS, TransitionRule(next_state=State.MAP_STATS))
		add(State.MAP_STATS, EventType.BACK_LONG_PRESS, TransitionRule(next_state=State.MAP_SELECT))

		# REGION_SELECT
		add(State.REGION_SELECT, EventType.NAV_PRESS, TransitionRule(next_state=State.REGION_SELECT, action=self._action_region_next))
		add(State.REGION_SELECT, EventType.CONFIRM_PRESS, TransitionRule(next_state=State.PREVIEW))
		add(State.REGION_SELECT, EventType.BACK_LONG_PRESS, TransitionRule(next_state=State.MAP_SELECT))
		add(State.REGION_SELECT, EventType.NAV_LONG_PRESS, TransitionRule(next_state=State.STATS, action=self._action_stats_page_reset))

		# STATS
		add(
			State.STATS,
			EventType.NAV_PRESS,
			TransitionRule(next_state=State.STATS, guard=self._has_multiple_stats_pages, action=self._action_stats_page_next),
		)
		add(State.STATS, EventType.NAV_PRESS, TransitionRule(next_state=State.STATS))
		add(State.STATS, EventType.BACK_LONG_PRESS, TransitionRule(next_state=State.REGION_SELECT))

		# PREVIEW
		add(State.PREVIEW, EventType.CONFIRM_PRESS, TransitionRule(next_state=State.CAPTURED, action=self._action_store_frame_if_present))
		add(
			State.PREVIEW,
			EventType.BACK_LONG_PRESS,
			TransitionRule(next_state=State.HOME, guard=self.guards.is_normal_mode),
		)
		add(
			State.PREVIEW,
			EventType.BACK_LONG_PRESS,
			TransitionRule(next_state=State.REGION_SELECT, guard=self.guards.is_sampling_mode),
		)

		# CAPTURED
		add(State.CAPTURED, EventType.CAPTURE_OK, TransitionRule(next_state=State.INFERENCING))
		add(
			State.CAPTURED,
			EventType.CAPTURE_FAIL,
			TransitionRule(next_state=State.PREVIEW, action=self._action_capture_fail),
		)

		# INFERENCING
		add(State.INFERENCING, EventType.INFER_OK, TransitionRule(next_state=State.DISPLAY, action=self._action_store_recognition))
		add(State.INFERENCING, EventType.INFER_FAIL, TransitionRule(next_state=State.PREVIEW, action=self._action_infer_fail))
		add(
			State.INFERENCING,
			EventType.TIMEOUT,
			TransitionRule(next_state=State.INFERENCING, follow_up_builder=self._follow_up_infer_fail),
		)

		# DISPLAY
		add(
			State.DISPLAY,
			EventType.TIMEOUT,
			TransitionRule(next_state=State.PREVIEW, guard=self.guards.is_normal_mode),
		)
		add(
			State.DISPLAY,
			EventType.BACK_LONG_PRESS,
			TransitionRule(next_state=State.PREVIEW, guard=self.guards.is_normal_mode),
		)
		add(
			State.DISPLAY,
			EventType.TIMEOUT,
			TransitionRule(next_state=State.RECORDING, guard=self._is_sampling_and_recognized),
		)
		add(
			State.DISPLAY,
			EventType.TIMEOUT,
			TransitionRule(next_state=State.PREVIEW, guard=self._is_sampling_and_unrecognized),
		)

		# RECORDING
		add(State.RECORDING, EventType.RECORD_OK, TransitionRule(next_state=State.PREVIEW))
		add(State.RECORDING, EventType.RECORD_FAIL, TransitionRule(next_state=State.PREVIEW, action=self._action_record_fail))
		add(
			State.RECORDING,
			EventType.TIMEOUT,
			TransitionRule(next_state=State.RECORDING, follow_up_builder=self._follow_up_record_fail),
		)

		# ERROR
		add(
			State.ERROR,
			EventType.CONFIRM_PRESS,
			TransitionRule(next_state=State.ERROR, action=self._action_request_retry),
		)
		add(
			State.ERROR,
			EventType.RETRY_PRESS,
			TransitionRule(
				next_state=State.HOME,
				guard=lambda ctx: self.guards.is_retryable(ctx) and self.guards.retry_success(ctx),
				action=self._action_retry_success,
			),
		)
		add(
			State.ERROR,
			EventType.RETRY_PRESS,
			TransitionRule(
				next_state=State.ERROR,
				guard=lambda ctx: self.guards.is_retryable(ctx) and self.guards.retry_failed(ctx),
			),
		)
		add(
			State.ERROR,
			EventType.RETRY_PRESS,
			TransitionRule(next_state=State.ERROR, guard=self.guards.is_not_retryable),
		)

		# Global SYSTEM_ERROR recovery path.
		for state in State:
			add(state, EventType.SYSTEM_ERROR, TransitionRule(next_state=State.ERROR, action=self._action_set_system_error))

		return rules

	@staticmethod
	def _action_toggle_home_option(ctx: StateContext, _event: Event) -> None:
		ctx.toggle_home_option()
		ctx.home_option_dirty = True

	@staticmethod
	def _action_set_mode_normal(ctx: StateContext, _event: Event) -> None:
		ctx.mode = MODE_NORMAL

	@staticmethod
	def _action_set_mode_sampling(ctx: StateContext, _event: Event) -> None:
		ctx.mode = MODE_SAMPLING

	@staticmethod
	def _action_clear_error(ctx: StateContext, _event: Event) -> None:
		ctx.clear_error()

	@staticmethod
	def _action_update_retryable_from_error(ctx: StateContext, _event: Event) -> None:
		ctx.error_is_retryable = bool(ctx.last_error and ctx.last_error.retryable)

	@staticmethod
	def _action_map_next(ctx: StateContext, _event: Event) -> None:
		if not ctx.available_maps:
			return
		current = 0 if ctx.selected_map_index is None else ctx.selected_map_index
		next_index = (current + 1) % len(ctx.available_maps)
		ctx.selected_map_index = next_index
		map_item = ctx.available_maps[next_index]
		ctx.selected_map_id = str(map_item.get("map_id") or map_item.get("id") or "") or None
		# Region selection belongs to a specific map and must be refreshed after map switch.
		ctx.selected_region_index = None
		ctx.selected_region_id = None
		ctx.selected_map_stats_page_index = 0
		ctx.current_map_stats_snapshot = None

	@staticmethod
	def _action_region_next(ctx: StateContext, _event: Event) -> None:
		if not ctx.available_regions:
			return
		current = 0 if ctx.selected_region_index is None else ctx.selected_region_index
		next_index = (current + 1) % len(ctx.available_regions)
		ctx.selected_region_index = next_index
		region_item = ctx.available_regions[next_index]
		ctx.selected_region_id = str(region_item.get("region_id") or region_item.get("id") or "") or None

	@staticmethod
	def _action_stats_page_reset(ctx: StateContext, _event: Event) -> None:
		ctx.selected_stats_page_index = 0

	@staticmethod
	def _action_stats_page_next(ctx: StateContext, _event: Event) -> None:
		snapshot = ctx.current_stats_snapshot
		if snapshot is None:
			return
		if snapshot.total_pages <= 1:
			return
		ctx.selected_stats_page_index = (ctx.selected_stats_page_index + 1) % snapshot.total_pages

	@staticmethod
	def _action_map_stats_page_reset(ctx: StateContext, _event: Event) -> None:
		ctx.selected_map_stats_page_index = 0

	@staticmethod
	def _action_map_stats_page_next(ctx: StateContext, _event: Event) -> None:
		snapshot = ctx.current_map_stats_snapshot
		if snapshot is None:
			return
		if snapshot.total_pages <= 1:
			return
		ctx.selected_map_stats_page_index = (ctx.selected_map_stats_page_index + 1) % snapshot.total_pages

	@staticmethod
	def _action_store_frame_if_present(ctx: StateContext, event: Event) -> None:
		if "frame" in event.payload:
			ctx.last_captured_frame = event.payload["frame"]

	@staticmethod
	def _action_capture_fail(ctx: StateContext, event: Event) -> None:
		reason = str(event.payload.get("reason", "capture_failed"))
		ctx.set_error(ErrorInfo(error_type="CameraError", message=reason, retryable=True))
		ctx.preview_error_flash_pending = True

	@staticmethod
	def _action_infer_fail(ctx: StateContext, event: Event) -> None:
		if ctx.last_error is None:
			reason = str(event.payload.get("reason", "infer_failed"))
			ctx.set_error(InferenceError(reason, retryable=False))
		ctx.preview_error_flash_pending = True

	@staticmethod
	def _action_record_fail(ctx: StateContext, event: Event) -> None:
		if ctx.last_error is None:
			reason = str(event.payload.get("reason", "record_failed"))
			ctx.set_error(StorageError(reason, retryable=False))
		ctx.preview_error_flash_pending = True

	@staticmethod
	def _action_store_recognition(ctx: StateContext, event: Event) -> None:
		result = event.payload.get("recognition_result")
		if isinstance(result, RecognitionResult):
			ctx.last_recognition_result = result
			return
		if isinstance(result, dict):
			ctx.last_recognition_result = RecognitionResult(
				class_id=result.get("class_id"),
				plant_key=result.get("plant_key"),
				plant_name=result.get("plant_name"),
				display_name=result.get("display_name"),
				confidence=float(result.get("confidence", 0.0)),
				is_recognized=bool(result.get("is_recognized", False)),
				source=str(result.get("source") or "local"),
				fallback_used=bool(result.get("fallback_used", False)),
				raw_label_name=result.get("raw_label_name"),
				catalog_mapped=bool(result.get("catalog_mapped", False)),
				top3=result.get("top3", []),
			)

	@staticmethod
	def _action_retry_success(ctx: StateContext, _event: Event) -> None:
		ctx.clear_error()
		ctx.retry_success = False
		ctx.retry_requested = False

	@staticmethod
	def _action_request_retry(ctx: StateContext, _event: Event) -> None:
		ctx.retry_requested = True

	@staticmethod
	def _action_set_system_error(ctx: StateContext, event: Event) -> None:
		message = str(event.payload.get("message", "system_error"))
		details = event.payload.get("details")
		ctx.set_error(ErrorInfo(error_type="SystemError", message=message, retryable=False, details=details or {}))

	def _is_sampling_and_recognized(self, ctx: StateContext) -> bool:
		return self.guards.is_sampling_mode(ctx) and self.guards.is_recognized(ctx)

	def _is_sampling_and_unrecognized(self, ctx: StateContext) -> bool:
		return self.guards.is_sampling_mode(ctx) and self.guards.is_unrecognized(ctx)

	@staticmethod
	def _has_multiple_stats_pages(ctx: StateContext) -> bool:
		return bool(ctx.current_stats_snapshot and ctx.current_stats_snapshot.total_pages > 1)

	@staticmethod
	def _has_multiple_map_stats_pages(ctx: StateContext) -> bool:
		return bool(ctx.current_map_stats_snapshot and ctx.current_map_stats_snapshot.total_pages > 1)

	@staticmethod
	def _follow_up_infer_fail(_ctx: StateContext, _event: Event) -> list[Event]:
		return [
			Event(
				EventType.INFER_FAIL,
				source="TimeoutScheduler",
				payload={"reason": "infer_timeout"},
			)
		]

	@staticmethod
	def _follow_up_record_fail(_ctx: StateContext, _event: Event) -> list[Event]:
		return [
			Event(
				EventType.RECORD_FAIL,
				source="TimeoutScheduler",
				payload={"reason": "record_timeout"},
			)
		]


