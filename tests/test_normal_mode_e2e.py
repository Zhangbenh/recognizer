from __future__ import annotations

import pytest

from application.events import Event, EventType
from application.states import State
from domain.errors import CloudTimeoutError, InferenceError
from infrastructure.cloud.baidu_plant_client import BaiduPlantCandidate, BaiduPlantResponse
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter, InferenceOutput


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


@pytest.fixture
def normal_controller_factory():
	import main as app_main
	from infrastructure.logging.logger import create_logger

	controllers = []

	def _build(
		*,
		cloud_outcome: BaiduPlantResponse | Exception | object = _USE_DEFAULT,
		strategy: str = "cloud_first",
		inference_output: InferenceOutput | None = None,
	):
		build_kwargs = {}
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
			logger=create_logger(name="recognizer.tests.normal.v11", level="ERROR"),
			**build_kwargs,
		)
		controllers.append(controller)
		return controller

	yield _build

	for controller in controllers:
		controller.stop()


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
	assert ctx.last_recognition_result.source == "cloud"
	assert ctx.last_recognition_result.fallback_used is False
	assert ctx.last_recognition_result.plant_key == "aloevera"
	assert ctx.last_recognition_result.raw_label_name == "芦荟"
	assert ctx.last_recognition_result.catalog_mapped is True
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

	first_count = sum("非致命错误信息: infer boom" in chunk for chunk in emitted)
	assert first_count == 1

	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(mock_controller, State.DISPLAY)
	mock_controller._state_machine.enqueue(Event(EventType.TIMEOUT, source="test"))
	_tick_until_state(mock_controller, State.PREVIEW)

	second_count = sum("非致命错误信息: infer boom" in chunk for chunk in emitted)
	assert second_count == 1
	assert mock_controller._state_machine.context.last_error is None


def test_normal_mode_cloud_failure_falls_back_to_local(normal_controller_factory) -> None:
	controller = normal_controller_factory(
		cloud_outcome=CloudTimeoutError("cloud request timed out", retryable=True),
	)

	_tick_until_state(controller, State.HOME)
	keyboard = controller._input_adapter
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)

	result = controller._state_machine.context.last_recognition_result
	assert result is not None
	assert result.is_recognized is True
	assert result.source == "local"
	assert result.fallback_used is True
	assert result.plant_key == "aloevera"
	assert result.display_name == "芦荟"
	assert result.catalog_mapped is True


def test_normal_mode_all_fail_returns_unrecognized_result(normal_controller_factory) -> None:
	controller = normal_controller_factory(
		cloud_outcome=CloudTimeoutError("cloud request timed out", retryable=True),
		inference_output=InferenceOutput(class_id=0, confidence=0.12, top3=[(0, 0.12)]),
	)

	_tick_until_state(controller, State.HOME)
	keyboard = controller._input_adapter
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.PREVIEW)
	keyboard.push_simulated_event("BTN1_SHORT")
	_tick_until_state(controller, State.DISPLAY)

	result = controller._state_machine.context.last_recognition_result
	assert result is not None
	assert result.is_recognized is False
	assert result.source == "local"
	assert result.fallback_used is True
	assert result.plant_key is None
	assert result.display_name is None
	assert result.catalog_mapped is False
