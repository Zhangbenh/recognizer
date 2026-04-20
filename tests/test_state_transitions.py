from __future__ import annotations

from application.events import Event, EventType
from application.state_context import StateContext
from application.state_machine import StateMachine
from application.states import State
from application.transition_engine import TransitionEngine, ValidationResult
from domain.models import ErrorInfo


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
