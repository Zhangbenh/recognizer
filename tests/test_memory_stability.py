"""A3: 内存稳定性测试 — 使用 tracemalloc 验证 100 次 mock 采样循环后内存增长受控。"""
from __future__ import annotations

import tracemalloc
from typing import NamedTuple

import pytest

from application.events import Event, EventType
from application.states import State


# ── helpers ──────────────────────────────────────────────────────────────────

def _tick_until_state(controller, target_state: State, *, max_ticks: int = 400) -> None:
	for _ in range(max_ticks):
		controller.tick()
		if controller._state_machine.current_state == target_state:
			return
	raise AssertionError(f"did not reach {target_state.value} within {max_ticks} ticks")


class _MemSnapshot(NamedTuple):
	cycle: int
	current_kb: float
	peak_kb: float


# ── A3 test ───────────────────────────────────────────────────────────────────

MEMORY_GROWTH_LIMIT_KB = 2048  # 2 MB 上限（验收判据）
SNAPSHOT_INTERVAL = 20         # 每 20 次循环采样一次内存
TOTAL_CYCLES = 100


def test_memory_stable_over_100_sampling_cycles(mock_controller) -> None:
	"""100 次 mock 采样全循环（PREVIEW→DISPLAY→TIMEOUT→PREVIEW），
	总内存增长 < 2MB，无对象积累导致的持续线性增长。"""
	keyboard = mock_controller._input_adapter
	_tick_until_state(mock_controller, State.HOME)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.PREVIEW)

	tracemalloc.start()
	snapshots: list[_MemSnapshot] = []

	baseline_current, baseline_peak = tracemalloc.get_traced_memory()

	for cycle in range(TOTAL_CYCLES):
		# PREVIEW → DISPLAY（单次完整识别）
		keyboard.push_simulated_event("BTN1_SHORT")
		_tick_until_state(mock_controller, State.DISPLAY, max_ticks=500)

		# DISPLAY → PREVIEW（TIMEOUT 驱动）
		mock_controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="mem_test"))
		_tick_until_state(mock_controller, State.PREVIEW, max_ticks=500)

		if (cycle + 1) % SNAPSHOT_INTERVAL == 0:
			current, peak = tracemalloc.get_traced_memory()
			snapshots.append(_MemSnapshot(
				cycle=cycle + 1,
				current_kb=current / 1024,
				peak_kb=peak / 1024,
			))

	final_current, final_peak = tracemalloc.get_traced_memory()
	tracemalloc.stop()

	growth_kb = (final_current - baseline_current) / 1024
	assert growth_kb < MEMORY_GROWTH_LIMIT_KB, (
		f"memory growth {growth_kb:.1f} KB exceeds limit {MEMORY_GROWTH_LIMIT_KB} KB "
		f"after {TOTAL_CYCLES} cycles"
	)

	# 检查无持续线性增长：后 40 次与前 20 次的平均内存差不超过 1MB
	if len(snapshots) >= 4:
		early_avg = sum(s.current_kb for s in snapshots[:2]) / 2
		late_avg = sum(s.current_kb for s in snapshots[-2:]) / 2
		linear_growth_kb = late_avg - early_avg
		assert linear_growth_kb < 1024, (
			f"linear memory growth detected: early={early_avg:.1f}KB late={late_avg:.1f}KB "
			f"delta={linear_growth_kb:.1f}KB"
		)
