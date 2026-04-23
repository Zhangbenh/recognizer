from __future__ import annotations

import pytest

from application.events import Event, EventType
from application.states import State
from domain.errors import CloudTimeoutError
from infrastructure.cloud.baidu_plant_client import BaiduPlantCandidate, BaiduPlantResponse
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter, InferenceOutput
from presentation.view_models import build_view_model


_USE_DEFAULT = object()


class _ScenarioSystemConfigRepository:
	def __init__(self, *, strategy: str) -> None:
		self._base = SystemConfigRepository()
		self._strategy = strategy

	def recognition_strategy(self) -> str:
		return self._strategy

	def __getattr__(self, name: str):
		return getattr(self._base, name)


class _CloudClientStub:
	def __init__(self, outcome: BaiduPlantResponse | Exception) -> None:
		self._outcome = outcome

	def recognize_image_bytes(self, image_bytes: bytes, *, baike_num: int = 0) -> BaiduPlantResponse:
		_ = image_bytes, baike_num
		if isinstance(self._outcome, Exception):
			raise self._outcome
		return self._outcome


class _InferenceStub(BaseInferenceAdapter):
	def __init__(self, *, output: InferenceOutput) -> None:
		self._output = output
		self._loaded = False

	@property
	def is_loaded(self) -> bool:
		return self._loaded

	def load_model(self, model_path: str) -> None:
		_ = model_path
		self._loaded = True

	def infer(self, image) -> InferenceOutput:
		_ = image
		return self._output

	def close(self) -> None:
		self._loaded = False


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

def isolated_sampling_controller_factory(tmp_path, monkeypatch):
	import main as app_main
	from infrastructure.logging.logger import create_logger
	from infrastructure.storage.json_storage_adapter import JsonStorageAdapter

	stats_file = tmp_path / "sampling_records.json"

	def _json_adapter_factory(file_path: str, default_value=None, pretty: bool = False):
		_ = file_path
		return JsonStorageAdapter(str(stats_file), default_value=default_value, pretty=pretty)

	monkeypatch.setattr(app_main, "JsonStorageAdapter", _json_adapter_factory)

	controllers = []

	def _build(
		*,
		cloud_outcome: BaiduPlantResponse | Exception | object = _USE_DEFAULT,
		strategy: str = "cloud_first",
		inference_output: InferenceOutput | None = None,
	):
		build_kwargs = {"storage_adapter_factory": _json_adapter_factory}
		if cloud_outcome is not _USE_DEFAULT:
			build_kwargs["baidu_plant_client"] = _CloudClientStub(cloud_outcome)
		if strategy != "cloud_first":
			build_kwargs["system_config_repository"] = _ScenarioSystemConfigRepository(strategy=strategy)
		if inference_output is not None:
			build_kwargs["inference_adapter"] = _InferenceStub(output=inference_output)

		controller = app_main.build_controller(
			runtime_backend="mock",
			input_backend="keyboard",
			ui_backend="text",
			logger=create_logger(name="recognizer.tests.phase5", level="ERROR"),
			**build_kwargs,
		)
		controllers.append(controller)
		return controller

	yield _build

	for controller in controllers:
		controller.stop()


@pytest.fixture
def isolated_sampling_controller(isolated_sampling_controller_factory):
	return isolated_sampling_controller_factory()


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
		assert ctx.last_recognition_result.source == "cloud"
		assert ctx.last_recognition_result.fallback_used is False
		assert ctx.last_recognition_result.plant_key == "aloevera"

		controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
		_tick_until(controller, lambda state: state == State.PREVIEW, max_ticks=500)

	# PREVIEW -> REGION_SELECT -> MAP_SELECT -> MAP_STATS
	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)
	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.MAP_SELECT)
	keyboard.push_simulated_event("BTN1_LONG")
	_tick_until_state(controller, State.MAP_STATS)

	map_snapshot = ctx.current_map_stats_snapshot
	assert map_snapshot is not None
	assert map_snapshot.map_id == ctx.selected_map_id
	assert len(map_snapshot.items) == 1
	assert map_snapshot.items[0].plant_key == "aloevera"
	assert map_snapshot.items[0].display_name == "芦荟"

	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.MAP_SELECT)

	# PREVIEW -> REGION_SELECT -> STATS
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)

	keyboard.push_simulated_event("BTN1_LONG")
	_tick_until_state(controller, State.STATS)

	snapshot = ctx.current_stats_snapshot
	assert snapshot is not None
	assert snapshot.region_id == selected_region_id
	assert len(snapshot.items) == 1
	assert snapshot.items[0].plant_key == "aloevera"
	assert snapshot.items[0].display_name == "芦荟"
	assert snapshot.items[0].count == 2

	# STATS page NAV should stay in STATS and BACK_LONG should return REGION_SELECT.
	keyboard.push_simulated_event("BTN2_SHORT")
	_tick_until_state(controller, State.STATS)

	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)


def test_record_fail_preview_warning_flashes_once_then_clears(isolated_sampling_controller) -> None:
	controller = isolated_sampling_controller
	ctx = controller._state_machine.context
	keyboard = controller._input_adapter

	emitted: list[str] = []
	controller._renderer._emit = lambda lines: emitted.append("\n".join(lines))

	_tick_until_state(controller, State.HOME)

	keyboard.push_simulated_event("BTN2_SHORT")
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)

	fallback_region_id = str(ctx.available_regions[0].get("region_id") or "")
	ctx.selected_region_id = None

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)
	controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(controller, State.PREVIEW)

	first_count = sum("非致命错误信息: missing_region_id" in chunk for chunk in emitted)
	assert first_count == 1

	ctx.selected_region_id = fallback_region_id
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)
	controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(controller, State.PREVIEW)

	second_count = sum("非致命错误信息: missing_region_id" in chunk for chunk in emitted)
	assert second_count == 1
	assert ctx.last_error is None


def test_sampling_mode_map_selection_exposes_thumbnail_entry_points(isolated_sampling_controller) -> None:
	controller = isolated_sampling_controller
	ctx = controller._state_machine.context
	keyboard = controller._input_adapter

	_tick_until_state(controller, State.HOME)
	keyboard.push_simulated_event("BTN2_SHORT")
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)

	assert ctx.available_maps
	assert str(ctx.available_maps[0].get("thumbnail_path") or "").endswith(".png")
	map_vm = build_view_model(State.MAP_SELECT, ctx)
	assert str(map_vm["selected_map_thumbnail_path"] or "").endswith(".png")
	assert len(map_vm["map_items"]) >= 1

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)
	assert ctx.available_regions
	assert str(ctx.available_regions[0].get("thumbnail_path") or "").endswith(".png")
	region_vm = build_view_model(State.REGION_SELECT, ctx)
	assert str(region_vm["selected_region_thumbnail_path"] or "").endswith(".png")
	assert len(region_vm["region_items"]) >= 1


def test_sampling_mode_cloud_failure_falls_back_to_local_and_records(isolated_sampling_controller_factory) -> None:
	controller = isolated_sampling_controller_factory(
		cloud_outcome=CloudTimeoutError("cloud request timed out", retryable=True),
	)
	ctx = controller._state_machine.context
	keyboard = controller._input_adapter

	_tick_until_state(controller, State.HOME)
	keyboard.push_simulated_event("BTN2_SHORT")
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)
	selected_region_id = ctx.available_regions[0]["region_id"]
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)

	result = ctx.last_recognition_result
	assert result is not None
	assert result.is_recognized is True
	assert result.source == "local"
	assert result.fallback_used is True
	assert result.plant_key == "aloevera"

	controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)
	assert ctx.selected_region_id == selected_region_id
	keyboard.push_simulated_event("BTN1_LONG")
	_tick_until_state(controller, State.STATS)

	snapshot = ctx.current_stats_snapshot
	assert snapshot is not None
	assert [item.plant_key for item in snapshot.items] == ["aloevera"]
	assert snapshot.items[0].count == 1


def test_sampling_mode_all_fail_skips_recording_and_map_stats_stay_empty(isolated_sampling_controller_factory) -> None:
	controller = isolated_sampling_controller_factory(
		cloud_outcome=CloudTimeoutError("cloud request timed out", retryable=True),
		inference_output=InferenceOutput(class_id=0, confidence=0.12, top3=[(0, 0.12)]),
	)
	ctx = controller._state_machine.context
	keyboard = controller._input_adapter

	_tick_until_state(controller, State.HOME)
	keyboard.push_simulated_event("BTN2_SHORT")
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)

	result = ctx.last_recognition_result
	assert result is not None
	assert result.is_recognized is False
	assert result.source == "local"
	assert result.fallback_used is True

	controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)
	keyboard.push_simulated_event("BTN1_LONG")
	_tick_until_state(controller, State.STATS)
	assert ctx.current_stats_snapshot is not None
	assert ctx.current_stats_snapshot.items == []

	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.REGION_SELECT)
	keyboard.push_simulated_event("BTN2_LONG")
	_tick_until_state(controller, State.MAP_SELECT)
	keyboard.push_simulated_event("BTN1_LONG")
	_tick_until_state(controller, State.MAP_STATS)
	assert ctx.current_map_stats_snapshot is not None
	assert ctx.current_map_stats_snapshot.items == []


# ── T3-4: DISPLAY 采样模式下 BTN2_LONG 不得跳过记录链路 ──────────────────────────

def test_display_sampling_mode_back_long_does_not_skip_recording(isolated_sampling_controller) -> None:
	"""DISPLAY 处于采样模式时，BTN2_LONG (BACK_LONG_PRESS) 不得改变状态；
	随后 TIMEOUT 应按采样规则（识别成功→RECORDING→PREVIEW，未识别→PREVIEW）流转，
	不可绕过记录链路。"""
	controller = isolated_sampling_controller
	ctx = controller._state_machine.context
	keyboard = controller._input_adapter

	# Navigate to DISPLAY in sampling mode
	_tick_until_state(controller, State.HOME)
	keyboard.push_simulated_event("BTN2_SHORT")
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.MAP_SELECT)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.REGION_SELECT)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)

	assert ctx.mode == "sampling"
	assert ctx.last_recognition_result is not None
	is_recognized = ctx.last_recognition_result.is_recognized

	# BTN2_LONG → BACK_LONG_PRESS: guard is_normal_mode 在采样模式失败 → 状态必须保持 DISPLAY
	keyboard.push_simulated_event("BTN2_LONG")
	for _ in range(50):
		controller.tick()
	assert controller._state_machine.current_state == State.DISPLAY, (
		"BTN2_LONG in sampling DISPLAY must not change state (recording chain must not be skipped)"
	)

	# 验证 TIMEOUT 触发采样规则流转：RECORDING（识别成功）或 PREVIEW（未识别）→ 最终进入 PREVIEW
	# RECORDING→PREVIEW 在同一 tick 内完成，故用 _tick_until 等待状态离开 DISPLAY
	controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until(controller, lambda s: s != State.DISPLAY, max_ticks=200)

	final_state = controller._state_machine.current_state
	assert final_state == State.PREVIEW, (
		f"after TIMEOUT in sampling DISPLAY, expected PREVIEW (via RECORDING if recognized), got {final_state.value}"
	)
	if is_recognized:
		# 识别成功路径必须经过 RECORDING，记录链路不可被跳过 → 无 DataError / StorageError
		assert ctx.last_error is None, (
			f"recording chain must complete without error when is_recognized=True, got {ctx.last_error}"
		)
