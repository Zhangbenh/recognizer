from __future__ import annotations

from time import perf_counter
from typing import NamedTuple

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


# ── A1: 持续负载性能回归（50次连续循环，p95 不超预算）──────────────────────────

class _Sample(NamedTuple):
	capture_s: float
	infer_s: float
	full_flow_s: float


def _p95(values: list[float]) -> float:
	sorted_vals = sorted(values)
	idx = max(0, int(len(sorted_vals) * 0.95) - 1)
	return sorted_vals[idx]


def test_sustained_50_cycles_performance_within_budget(mock_controller) -> None:
	"""50 次连续 mock capture+infer+full_flow，p95 不超 system_config 三项预算。"""
	budget = SystemConfigRepository().performance_budget()
	capture_budget_s = float(budget["capture_s"])
	infer_budget_s = float(budget["infer_s"])
	full_flow_budget_s = float(budget["full_flow_s"])

	_tick_until_state(mock_controller, State.HOME)

	keyboard = mock_controller._input_adapter
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.PREVIEW)

	recognition_service = mock_controller._recognition_service
	samples: list[_Sample] = []
	cycles = 50

	for i in range(cycles):
		t0 = perf_counter()
		frame = recognition_service.capture_frame()
		capture_elapsed = perf_counter() - t0

		t1 = perf_counter()
		recognition_service.recognize(frame)
		infer_elapsed = perf_counter() - t1

		full_start = perf_counter()
		keyboard.push_simulated_event("BTN1_SHORT")
		_tick_until_state(mock_controller, State.DISPLAY, max_ticks=400)
		full_elapsed = perf_counter() - full_start

		from application.events import Event, EventType
		mock_controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
		_tick_until_state(mock_controller, State.PREVIEW, max_ticks=400)

		samples.append(_Sample(capture_elapsed, infer_elapsed, full_elapsed))

	capture_p95 = _p95([s.capture_s for s in samples])
	infer_p95 = _p95([s.infer_s for s in samples])
	full_p95 = _p95([s.full_flow_s for s in samples])

	assert capture_p95 <= capture_budget_s, (
		f"sustained capture p95={capture_p95:.4f}s exceeds budget={capture_budget_s}s"
	)
	assert infer_p95 <= infer_budget_s, (
		f"sustained infer p95={infer_p95:.4f}s exceeds budget={infer_budget_s}s"
	)
	assert full_p95 <= full_flow_budget_s, (
		f"sustained full_flow p95={full_p95:.4f}s exceeds budget={full_flow_budget_s}s"
	)



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
