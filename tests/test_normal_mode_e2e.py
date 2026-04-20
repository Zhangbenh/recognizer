from __future__ import annotations

from application.events import Event, EventType
from application.states import State


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
