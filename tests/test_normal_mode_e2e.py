from __future__ import annotations

from application.events import Event, EventType
from application.states import State
from domain.errors import InferenceError


def _tick_until_state(controller, target_state: State, *, max_ticks: int = 300) -> None:
	for _ in range(max_ticks):
		controller.tick()
		if controller._state_machine.current_state == target_state:
			return
	raise AssertionError(f"did not reach state {target_state.value} within {max_ticks} ticks")


def test_normal_mode_end_to_end_flow(mock_controller) -> None:
	_tick_until_state(mock_controller, State.HOME)

	keyboard = mock_controller._input_adapter
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.PREVIEW)

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.DISPLAY)

	ctx = mock_controller._state_machine.context
	assert ctx.mode == "normal"
	assert ctx.last_recognition_result is not None
	assert ctx.last_recognition_result.is_recognized is True
	assert ctx.last_recognition_result.display_name is not None

	# Force TIMEOUT to complete DISPLAY -> PREVIEW quickly in unit test.
	mock_controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(mock_controller, State.PREVIEW)


def test_infer_fail_preview_warning_flashes_once_then_clears(mock_controller) -> None:
	_tick_until_state(mock_controller, State.HOME)

	emitted: list[str] = []
	mock_controller._renderer._emit = lambda lines: emitted.append("\n".join(lines))

	keyboard = mock_controller._input_adapter
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.PREVIEW)

	service = mock_controller._recognition_service
	original_recognize = service.recognize

	def _fail_once(frame):
		service.recognize = original_recognize
		raise InferenceError("infer boom", retryable=False)

	service.recognize = _fail_once
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.PREVIEW)

	first_count = sum("non_fatal_error_message: infer boom" in chunk for chunk in emitted)
	assert first_count == 1

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.DISPLAY)
	mock_controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(mock_controller, State.PREVIEW)

	second_count = sum("non_fatal_error_message: infer boom" in chunk for chunk in emitted)
	assert second_count == 1
	assert mock_controller._state_machine.context.last_error is None
