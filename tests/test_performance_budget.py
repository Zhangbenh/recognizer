from __future__ import annotations

from time import perf_counter

from application.states import State
from infrastructure.config.system_config_repository import SystemConfigRepository


def _tick_until_state(controller, target_state: State, *, max_ticks: int = 300) -> None:
	for _ in range(max_ticks):
		controller.tick()
		if controller._state_machine.current_state == target_state:
			return
	raise AssertionError(f"did not reach state {target_state.value} within {max_ticks} ticks")


def test_mock_runtime_meets_performance_budget(mock_controller) -> None:
	budget = SystemConfigRepository().performance_budget()
	capture_budget_s = float(budget["capture_s"])
	infer_budget_s = float(budget["infer_s"])
	full_flow_budget_s = float(budget["full_flow_s"])

	_tick_until_state(mock_controller, State.HOME)

	recognition_service = mock_controller._recognition_service

	capture_start = perf_counter()
	frame = recognition_service.capture_frame()
	capture_elapsed = perf_counter() - capture_start

	infer_start = perf_counter()
	result = recognition_service.recognize(frame)
	infer_elapsed = perf_counter() - infer_start

	assert result.is_recognized is True
	assert capture_elapsed <= capture_budget_s, (
		f"capture budget exceeded: elapsed={capture_elapsed:.4f}s budget={capture_budget_s:.4f}s"
	)
	assert infer_elapsed <= infer_budget_s, (
		f"infer budget exceeded: elapsed={infer_elapsed:.4f}s budget={infer_budget_s:.4f}s"
	)

	keyboard = mock_controller._input_adapter
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.PREVIEW)

	full_flow_start = perf_counter()
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.DISPLAY)
	full_flow_elapsed = perf_counter() - full_flow_start

	assert full_flow_elapsed <= full_flow_budget_s, (
		f"full flow budget exceeded: elapsed={full_flow_elapsed:.4f}s budget={full_flow_budget_s:.4f}s"
	)
