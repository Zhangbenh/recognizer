from __future__ import annotations

import pytest

from application.events import Event, EventType
from application.states import State


def _tick_until_state(controller, target_state: State, *, max_ticks: int = 400) -> None:
	for _ in range(max_ticks):
		controller.tick()
		if controller._state_machine.current_state == target_state:
			return
	raise AssertionError(f"did not reach state {target_state.value} within {max_ticks} ticks")


def _tick_until(controller, predicate, *, max_ticks: int = 400) -> list[State]:
	visited: list[State] = []
	for _ in range(max_ticks):
		controller.tick()
		state = controller._state_machine.current_state
		visited.append(state)
		if predicate(state):
			return visited
	raise AssertionError(f"predicate did not match within {max_ticks} ticks, visited={visited[-10:]}")


@pytest.fixture
def isolated_sampling_controller(tmp_path, monkeypatch):
	import main as app_main
	from infrastructure.logging.logger import create_logger
	from infrastructure.storage.json_storage_adapter import JsonStorageAdapter

	stats_file = tmp_path / "sampling_records.json"

	def _json_adapter_factory(file_path: str, default_value=None, pretty: bool = False):
		_ = file_path
		return JsonStorageAdapter(str(stats_file), default_value=default_value, pretty=pretty)

	monkeypatch.setattr(app_main, "JsonStorageAdapter", _json_adapter_factory)

	logger = create_logger(name="recognizer.tests.phase5", level="ERROR")
	controller = app_main.build_controller(runtime_backend="mock", input_backend="keyboard", logger=logger)
	try:
		yield controller
	finally:
		controller.stop()


def test_sampling_mode_end_to_end_flow_and_stats(isolated_sampling_controller) -> None:
	controller = isolated_sampling_controller
	ctx = controller._state_machine.context
	keyboard = controller._input_adapter

	_tick_until_state(controller, State.HOME)

	# HOME(normal) -> HOME(sampling) -> MAP_SELECT
	keyboard.push_simulated_event("BTN2_SHORT")
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)
	assert ctx.mode == "sampling"

	# Switch one map to exercise map navigation and region reset behavior.
	original_map_id = ctx.selected_map_id
	keyboard.push_simulated_event("BTN2_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)
	assert ctx.selected_map_id != original_map_id
	assert ctx.selected_region_id is None

	# MAP_SELECT -> REGION_SELECT
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)
	assert ctx.selected_region_id is not None

	# Choose a non-default region index and enter PREVIEW.
	keyboard.push_simulated_event("BTN2_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)
	selected_region_id = ctx.selected_region_id
	assert selected_region_id is not None

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)

	# Run two sampling cycles and force DISPLAY timeout for deterministic tests.
	for _ in range(2):
		keyboard.push_simulated_event("BTN1_SHORT")
		_tick_until_state(controller, State.DISPLAY)
		assert ctx.last_recognition_result is not None
		assert ctx.last_recognition_result.is_recognized is True

		controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
		_tick_until(controller, lambda state: state == State.PREVIEW, max_ticks=500)

	# PREVIEW -> REGION_SELECT -> STATS
	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)

	keyboard.push_simulated_event("BTN1_LONG")
	_tick_until_state(controller, State.STATS)

	snapshot = ctx.current_stats_snapshot
	assert snapshot is not None
	assert snapshot.region_id == selected_region_id
	assert len(snapshot.items) == 1
	assert snapshot.items[0].plant_key == "aloevera"
	assert snapshot.items[0].count == 2

	# STATS page NAV should stay in STATS and BACK_LONG should return REGION_SELECT.
	keyboard.push_simulated_event("BTN2_SHORT")
	_tick_until_state(controller, State.STATS)

	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)
