from __future__ import annotations

import pytest

from application.events import EXTERNAL_EVENTS, Event, EventType
from application.error_policy import ErrorPolicy
from application.state_context import StateContext
from application.state_handlers.booting_handler import BootingHandler
from application.state_handlers.captured_handler import CapturedHandler
from application.state_handlers.error_handler import ErrorHandler
from application.state_handlers.home_handler import HomeHandler
from application.state_handlers.inferencing_handler import InferencingHandler
from application.state_handlers.map_select_handler import MapSelectHandler
from application.state_handlers.map_stats_handler import MapStatsHandler
from application.state_handlers.recording_handler import RecordingHandler
from application.state_machine import StateMachine
from application.states import State
from application.transition_engine import TransitionEngine, ValidationResult
from domain.errors import ReleaseGateError
from domain.models import ErrorInfo
from domain.models import RecognitionResult
from domain.sampling_recorder import SamplingRecorder
from domain.statistics_query_service import StatisticsQueryService
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository


def _apply(engine: TransitionEngine, state: State, event: Event, ctx: StateContext) -> State:
	plan = engine.plan_transition(state, event, ctx)
	assert plan.is_valid, f"event should be valid: {state=} {event.event_type=}"
	assert plan.guard_passed, f"guard should pass: {state=} {event.event_type=}"
	plan.action(ctx, event)
	return plan.next_state or state


def test_transition_engine_normal_mode_happy_path() -> None:
	ctx = StateContext()
	engine = TransitionEngine()
	state = State.HOME

	state = _apply(engine, state, Event(EventType.CONFIRM_PRESS, source="test"), ctx)
	assert state == State.PREVIEW
	assert ctx.mode == "normal"

	state = _apply(
		engine,
		state,
		Event(EventType.CONFIRM_PRESS, payload={"frame": {"dummy": True}}, source="test"),
		ctx,
	)
	assert state == State.CAPTURED
	assert ctx.last_captured_frame == {"dummy": True}

	state = _apply(engine, state, Event(EventType.CAPTURE_OK, source="test"), ctx)
	assert state == State.INFERENCING

	state = _apply(
		engine,
		state,
		Event(
			EventType.INFER_OK,
			payload={
				"recognition_result": {
					"class_id": 18,
					"plant_key": "paddy",
					"plant_name": "paddy",
					"display_name": "Paddy",
					"confidence": 0.86,
					"is_recognized": True,
					"top3": [(18, 0.86), (0, 0.08), (1, 0.06)],
				}
			},
			source="test",
		),
		ctx,
	)
	assert state == State.DISPLAY
	assert ctx.last_recognition_result is not None
	assert ctx.last_recognition_result.display_name == "Paddy"

	state = _apply(engine, state, Event(EventType.TIMEOUT, source="test"), ctx)
	assert state == State.PREVIEW


def test_transition_engine_sampling_entry_and_map_switch_resets_region() -> None:
	ctx = StateContext(
		available_maps=[
			{"map_id": "map_a"},
			{"map_id": "map_b"},
		],
		selected_map_index=0,
		selected_map_id="map_a",
		selected_region_index=3,
		selected_region_id="map_a_r4",
	)
	engine = TransitionEngine()
	state = State.HOME

	state = _apply(engine, state, Event(EventType.NAV_PRESS, source="test"), ctx)
	assert state == State.HOME
	assert ctx.selected_home_option == "sampling"

	state = _apply(engine, state, Event(EventType.CONFIRM_PRESS, source="test"), ctx)
	assert state == State.MAP_SELECT
	assert ctx.mode == "sampling"

	state = _apply(engine, state, Event(EventType.NAV_PRESS, source="test"), ctx)
	assert state == State.MAP_SELECT
	assert ctx.selected_map_id == "map_b"
	assert ctx.selected_region_id is None
	assert ctx.selected_region_index is None
	assert ctx.selected_map_stats_page_index == 0
	assert ctx.current_map_stats_snapshot is None


def test_state_machine_map_stats_round_trip_and_uses_map_aggregation(tmp_path) -> None:
	class _SamplingRepoStub:
		def __init__(self) -> None:
			self._maps = [
				{
					"map_id": "map_a",
					"display_name": "地图A",
					"regions": [
						{"region_id": "map_a_r1", "display_name": "区域1"},
						{"region_id": "map_a_r2", "display_name": "区域2"},
					],
				}
			]

		def list_maps(self):
			return self._maps

		def get_map(self, map_id: str):
			for item in self._maps:
				if item["map_id"] == map_id:
					return item
			return None

	class _LabelRepoStub:
		def load(self):
			return [
				{"index": 1, "plant_key": "banana", "display_name": "香蕉"},
				{"index": 18, "plant_key": "paddy", "display_name": "水稻"},
			]

	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	stats_service = StatisticsQueryService(
		stats_repository=repository,
		label_repository=_LabelRepoStub(),
		sampling_config_repository=_SamplingRepoStub(),
		page_size=1,
	)

	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=1,
			plant_key="banana",
			plant_name="banana",
			display_name="香蕉",
			confidence=0.61,
			is_recognized=True,
			top3=[(1, 0.61)],
		),
	)
	recorder.record(
		"map_a_r2",
		RecognitionResult(
			class_id=None,
			plant_key="cloud:wildflower",
			plant_name="wildflower",
			display_name="野花",
			confidence=0.88,
			is_recognized=True,
			source="cloud",
			catalog_mapped=False,
			top3=[],
		),
	)

	state_machine = StateMachine(
		initial_state=State.MAP_SELECT,
		context=StateContext(mode="sampling"),
		handlers={
			State.MAP_SELECT: MapSelectHandler(sampling_config_repository=_SamplingRepoStub()),
			State.MAP_STATS: MapStatsHandler(statistics_query_service=stats_service),
		},
	)
	state_machine.start()

	assert state_machine.context.selected_map_id == "map_a"

	state_machine.enqueue(Event(EventType.NAV_LONG_PRESS, source="test"))
	assert state_machine.process_next_event() is True
	assert state_machine.current_state == State.MAP_STATS
	assert state_machine.context.current_map_stats_snapshot is not None
	assert state_machine.context.current_map_stats_snapshot.map_id == "map_a"
	assert state_machine.context.current_map_stats_snapshot.total_region_count == 2
	assert [item.plant_key for item in state_machine.context.current_map_stats_snapshot.items] == [
		"banana",
		"cloud:wildflower",
	]
	assert state_machine.context.selected_map_stats_page_index == 0

	state_machine.enqueue(Event(EventType.NAV_PRESS, source="test"))
	assert state_machine.process_next_event() is True
	assert state_machine.current_state == State.MAP_STATS
	assert state_machine.context.selected_map_stats_page_index == 1

	state_machine.enqueue(Event(EventType.BACK_LONG_PRESS, source="test"))
	assert state_machine.process_next_event() is True
	assert state_machine.current_state == State.MAP_SELECT


def test_transition_engine_error_retry_success_goes_home() -> None:
	ctx = StateContext()
	ctx.last_error = ErrorInfo(error_type="InferenceError", message="temporary", retryable=True)
	ctx.error_is_retryable = True
	ctx.retry_success = True

	engine = TransitionEngine()
	state = _apply(engine, State.ERROR, Event(EventType.RETRY_PRESS, source="test"), ctx)
	assert state == State.HOME
	assert ctx.last_error is None
	assert ctx.error_is_retryable is False
	assert ctx.retry_success is False


def test_validate_event_illegal_internal_classification() -> None:
	engine = TransitionEngine()
	result = engine.validate_event(State.HOME, EventType.INFER_OK)
	assert result == ValidationResult.ILLEGAL_INTERNAL


def test_state_machine_illegal_internal_event_enqueues_system_error() -> None:
	sm = StateMachine(initial_state=State.HOME, context=StateContext())
	sm.start()

	sm.enqueue(Event(EventType.INFER_OK, source="test"))
	assert sm.process_next_event() is True
	assert sm.current_state == State.HOME

	assert sm.process_next_event() is True
	assert sm.current_state == State.ERROR


def test_home_handler_resets_option_on_return() -> None:
	ctx = StateContext(selected_home_option="sampling", home_option_dirty=False)

	HomeHandler().on_enter(ctx)

	assert ctx.selected_home_option == "normal"


def test_home_handler_preserves_toggle_on_self_loop_nav() -> None:
	ctx = StateContext(selected_home_option="sampling", home_option_dirty=True)

	HomeHandler().on_enter(ctx)

	assert ctx.selected_home_option == "sampling"
	assert ctx.home_option_dirty is False


def test_booting_handler_rejects_map_without_regions() -> None:
	class _ReleaseGateOk:
		def ensure_pass(self) -> None:
			return None

	class _RecognitionOk:
		def boot(self) -> None:
			return None

	class _SamplingRepoInvalid:
		def list_maps(self):
			return [{"map_id": "map_a", "display_name": "Map A", "regions": []}]

	ctx = StateContext()
	handler = BootingHandler(
		release_gate_service=_ReleaseGateOk(),
		recognition_service=_RecognitionOk(),
		sampling_config_repository=_SamplingRepoInvalid(),
	)

	events = handler.on_enter(ctx)

	assert len(events) == 1
	assert events[0].event_type == EventType.BOOT_FAIL
	assert ctx.last_error is not None
	assert ctx.last_error.error_type == "ConfigError"


def test_error_handler_executes_retry_when_requested() -> None:
	called = {"count": 0}

	def _retry_executor() -> None:
		called["count"] += 1

	ctx = StateContext(
		last_error=ErrorInfo(error_type="CameraError", message="boot fail", retryable=True),
		retry_requested=True,
	)
	handler = ErrorHandler(retry_executor=_retry_executor)

	events = handler.on_enter(ctx)

	assert called["count"] == 1
	assert ctx.retry_success is True
	assert len(events) == 1
	assert events[0].event_type == EventType.RETRY_PRESS


def test_error_handler_non_retryable_does_not_execute_retry() -> None:
	called = {"count": 0}

	def _retry_executor() -> None:
		called["count"] += 1

	ctx = StateContext(
		last_error=ErrorInfo(error_type="ReleaseGateError", message="blocked", retryable=False),
		retry_requested=True,
	)
	handler = ErrorHandler(retry_executor=_retry_executor)

	events = handler.on_enter(ctx)

	assert called["count"] == 0
	assert ctx.retry_success is False
	assert len(events) == 1
	assert events[0].event_type == EventType.RETRY_PRESS


def test_error_policy_release_gate_error_stays_in_error() -> None:
	policy = ErrorPolicy()
	err = ReleaseGateError("blocked by release gate", retryable=False)

	assert policy.is_retryable(err) is False
	assert policy.recovery_target(State.BOOTING, err) == State.ERROR


def test_captured_handler_missing_frame_sets_camera_error() -> None:
	ctx = StateContext(last_captured_frame=None)
	events = CapturedHandler().on_enter(ctx)

	assert len(events) == 1
	assert events[0].event_type == EventType.CAPTURE_FAIL
	assert ctx.last_error is not None
	assert ctx.last_error.error_type == "CameraError"


def test_inferencing_handler_missing_frame_sets_inference_error() -> None:
	class _RecognitionNeverUsed:
		def recognize(self, _frame):
			raise AssertionError("recognize should not be called without frame")

	ctx = StateContext(last_captured_frame=None)
	handler = InferencingHandler(recognition_service=_RecognitionNeverUsed())
	events = handler.on_enter(ctx)

	assert len(events) == 1
	assert events[0].event_type == EventType.INFER_FAIL
	assert ctx.last_error is not None
	assert ctx.last_error.error_type == "InferenceError"


def test_recording_handler_missing_region_sets_data_error() -> None:
	class _RecorderNeverUsed:
		def record(self, _region_id: str, _result: RecognitionResult) -> None:
			raise AssertionError("record should not be called without region")

	ctx = StateContext(
		selected_region_id=None,
		last_recognition_result=RecognitionResult(
			class_id=1,
			plant_key="paddy",
			plant_name="paddy",
			display_name="Paddy",
			confidence=0.9,
			is_recognized=True,
			top3=[(1, 0.9)],
		),
	)
	handler = RecordingHandler(sampling_recorder=_RecorderNeverUsed())
	events = handler.on_enter(ctx)

	assert len(events) == 1
	assert events[0].event_type == EventType.RECORD_FAIL
	assert ctx.last_error is not None
	assert ctx.last_error.error_type == "DataError"


# ── T3-1: INFERENCING 不可中断 ────────────────────────────────────────────────

@pytest.mark.parametrize(
	"intruding_event_type",
	[
		EventType.BACK_LONG_PRESS,
		EventType.NAV_PRESS,
		EventType.CONFIRM_PRESS,
		EventType.NAV_LONG_PRESS,
	],
	ids=["back_long", "nav", "confirm", "nav_long"],
)
def test_inferencing_ignores_external_input_and_stays_inferencing(
	intruding_event_type: EventType,
) -> None:
	"""INFERENCING 阶段外部按键不得中断推理，状态保持不变且不升级为 SYSTEM_ERROR。"""
	sm = StateMachine(initial_state=State.INFERENCING, context=StateContext())
	sm.start()

	for _ in range(5):
		sm.enqueue(Event(intruding_event_type, source="test"))

	for _ in range(5):
		assert sm.process_next_event() is True
		assert sm.current_state == State.INFERENCING, (
			f"INFERENCING 不得被 {intruding_event_type.value} 中断"
		)

	# 不可中断：外部事件被静默忽略，不应在队列中残留 SYSTEM_ERROR
	assert sm._event_queue.is_empty()


# ── T3-2: RECORDING 不可中断 ──────────────────────────────────────────────────

@pytest.mark.parametrize(
	"intruding_event_type",
	[
		EventType.BACK_LONG_PRESS,
		EventType.NAV_PRESS,
		EventType.CONFIRM_PRESS,
		EventType.NAV_LONG_PRESS,
	],
	ids=["back_long", "nav", "confirm", "nav_long"],
)
def test_recording_ignores_external_input_and_stays_recording(
	intruding_event_type: EventType,
) -> None:
	"""RECORDING 阶段外部按键不得中断录制，状态保持不变且不升级为 SYSTEM_ERROR。"""
	sm = StateMachine(initial_state=State.RECORDING, context=StateContext())
	sm.start()

	for _ in range(5):
		sm.enqueue(Event(intruding_event_type, source="test"))

	for _ in range(5):
		assert sm.process_next_event() is True
		assert sm.current_state == State.RECORDING, (
			f"RECORDING 不得被 {intruding_event_type.value} 中断"
		)

	assert sm._event_queue.is_empty()


# ── T3-3: 关键状态非法外部输入分类矩阵 ────────────────────────────────────────

@pytest.mark.parametrize(
	"locked_state",
	[State.INFERENCING, State.RECORDING, State.CAPTURED],
	ids=["inferencing", "recording", "captured"],
)
@pytest.mark.parametrize(
	"external_event_type",
	list(EXTERNAL_EVENTS),
	ids=[e.value for e in EXTERNAL_EVENTS],
)
def test_external_events_classified_as_illegal_external_in_locked_states(
	locked_state: State,
	external_event_type: EventType,
) -> None:
	"""INFERENCING / RECORDING / CAPTURED 不接受任何外部按键事件，校验结果应为 ILLEGAL_EXTERNAL。"""
	engine = TransitionEngine()
	result = engine.validate_event(locked_state, external_event_type)
	assert result == ValidationResult.ILLEGAL_EXTERNAL, (
		f"{locked_state.value} + {external_event_type.value} 应为 ILLEGAL_EXTERNAL，实际为 {result}"
	)
