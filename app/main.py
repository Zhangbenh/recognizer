"""Recognizer application entrypoint (Phase 3A minimal runnable loop)."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from application.input_mapper import InputMapper
from application.state_context import StateContext
from application.state_handlers import (
	BootingHandler,
	CapturedHandler,
	DisplayHandler,
	ErrorHandler,
	HomeHandler,
	InferencingHandler,
	MapSelectHandler,
	PreviewHandler,
	RecordingHandler,
	RegionSelectHandler,
	StatsHandler,
)
from application.state_machine import StateMachine
from application.states import State
from controller.app_controller import AppController
from domain.recognition_service import RecognitionService
from domain.release_gate_service import ReleaseGateService
from domain.sampling_recorder import SamplingRecorder
from domain.statistics_query_service import StatisticsQueryService
from infrastructure.camera.base_camera_adapter import BaseCameraAdapter
from infrastructure.camera.picamera2_adapter import Picamera2Adapter
from infrastructure.config.label_repository import LabelRepository
from infrastructure.config.model_manifest_repository import ModelManifestRepository
from infrastructure.config.sampling_config_repository import SamplingConfigRepository
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter, InferenceOutput
from infrastructure.inference.tflite_adapter import TFLiteAdapter
from infrastructure.input.gpio_button_adapter import GPIOButtonAdapter
from infrastructure.input.keyboard_adapter import KeyboardAdapter
from infrastructure.logging.logger import create_logger
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter
from presentation.renderer import Renderer


class MockCameraAdapter(BaseCameraAdapter):
	"""Development fallback camera adapter for desktop smoke tests."""

	def __init__(self) -> None:
		self._started = False

	@property
	def is_started(self) -> bool:
		return self._started

	def start(self) -> None:
		self._started = True

	def stop(self) -> None:
		self._started = False

	def capture_frame(self):
		if not self._started:
			raise RuntimeError("mock camera is not started")
		# Payload content is not used by the mock inference adapter.
		return {"mock": "frame"}

	def close(self) -> None:
		self._started = False


class MockInferenceAdapter(BaseInferenceAdapter):
	"""Development fallback inference adapter for desktop smoke tests."""

	def __init__(self, *, expected_output_classes: int = 30) -> None:
		self._expected_output_classes = expected_output_classes
		self._loaded = False

	@property
	def is_loaded(self) -> bool:
		return self._loaded

	def load_model(self, model_path: str) -> None:
		_ = model_path
		self._loaded = True

	def infer(self, image) -> InferenceOutput:
		_ = image
		if not self._loaded:
			raise RuntimeError("mock model not loaded")

		top3 = [(0, 0.92), (1, 0.05), (2, 0.03)]
		probs = [0.0] * self._expected_output_classes
		for class_id, confidence in top3:
			if 0 <= class_id < len(probs):
				probs[class_id] = confidence

		return InferenceOutput(
			class_id=0,
			confidence=0.92,
			top3=top3,
			probabilities=probs,
		)

	def close(self) -> None:
		self._loaded = False


def default_input_backend() -> str:
	return "keyboard" if os.name == "nt" else "gpio"


def build_runtime_adapters(
	*, runtime_backend: str, expected_output_classes: int
) -> tuple[BaseCameraAdapter, BaseInferenceAdapter]:
	if runtime_backend == "mock":
		return MockCameraAdapter(), MockInferenceAdapter(expected_output_classes=expected_output_classes)

	camera_adapter = Picamera2Adapter(
		width=480,
		height=320,
		rotation=180,
		swap_red_blue=True,
	)
	inference_adapter = TFLiteAdapter(expected_output_classes=expected_output_classes)
	return camera_adapter, inference_adapter


def build_input_adapter(*, input_backend: str, system_config: SystemConfigRepository):
	if input_backend == "keyboard":
		return KeyboardAdapter(enable_stdin_poll=True)

	if input_backend == "gpio":
		return GPIOButtonAdapter(
			btn1_pin=17,
			btn2_pin=18,
			long_press_ms=system_config.long_press_threshold_ms(),
			debounce_ms=system_config.capture_debounce_ms(),
		)

	raise ValueError(f"unsupported input backend: {input_backend}")


def build_controller(*, runtime_backend: str, input_backend: str, logger: logging.Logger) -> AppController:
	repo_root = Path(__file__).resolve().parents[1]
	data_file = repo_root / "data" / "sampling_records.json"

	label_repository = LabelRepository()
	model_manifest_repository = ModelManifestRepository()
	sampling_config_repository = SamplingConfigRepository()
	system_config_repository = SystemConfigRepository()
	storage_adapter = JsonStorageAdapter(str(data_file), default_value={"regions": {}}, pretty=True)

	expected_output_classes = model_manifest_repository.output_classes()
	camera_adapter, inference_adapter = build_runtime_adapters(
		runtime_backend=runtime_backend,
		expected_output_classes=expected_output_classes,
	)
	input_adapter = build_input_adapter(input_backend=input_backend, system_config=system_config_repository)

	recognition_service = RecognitionService(
		camera_adapter=camera_adapter,
		inference_adapter=inference_adapter,
		label_repository=label_repository,
		model_manifest_repository=model_manifest_repository,
		system_config_repository=system_config_repository,
		logger=logger,
	)
	release_gate_service = ReleaseGateService(
		model_manifest_repository=model_manifest_repository,
		system_config_repository=system_config_repository,
	)
	sampling_recorder = SamplingRecorder(storage_adapter=storage_adapter)
	statistics_query_service = StatisticsQueryService(storage_adapter=storage_adapter)

	handlers = {
		State.BOOTING: BootingHandler(
			release_gate_service=release_gate_service,
			recognition_service=recognition_service,
			sampling_config_repository=sampling_config_repository,
		),
		State.HOME: HomeHandler(),
		State.MAP_SELECT: MapSelectHandler(sampling_config_repository=sampling_config_repository),
		State.REGION_SELECT: RegionSelectHandler(sampling_config_repository=sampling_config_repository),
		State.PREVIEW: PreviewHandler(),
		State.CAPTURED: CapturedHandler(),
		State.INFERENCING: InferencingHandler(recognition_service=recognition_service),
		State.DISPLAY: DisplayHandler(),
		State.RECORDING: RecordingHandler(sampling_recorder=sampling_recorder),
		State.STATS: StatsHandler(statistics_query_service=statistics_query_service),
		State.ERROR: ErrorHandler(),
	}

	state_machine = StateMachine(context=StateContext(), handlers=handlers)
	input_mapper = InputMapper()
	renderer = Renderer(logger=logger)

	return AppController(
		state_machine=state_machine,
		input_adapter=input_adapter,
		input_mapper=input_mapper,
		renderer=renderer,
		recognition_service=recognition_service,
		release_gate_service=release_gate_service,
		logger=logger,
	)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Plant recognizer runtime")
	parser.add_argument(
		"--runtime",
		choices=("real", "mock"),
		default=os.getenv("RECOGNIZER_RUNTIME", "real"),
		help="runtime backend (real uses camera+tflite, mock runs desktop-safe)",
	)
	parser.add_argument(
		"--input",
		choices=("keyboard", "gpio"),
		default=os.getenv("RECOGNIZER_INPUT", default_input_backend()),
		help="input backend",
	)
	parser.add_argument("--max-ticks", type=int, default=None, help="optional max loop ticks for testing")
	parser.add_argument("--idle-sleep", type=float, default=0.02, help="sleep seconds when no work is done")
	parser.add_argument("--log-level", type=str, default=os.getenv("RECOGNIZER_LOG_LEVEL", "INFO"))
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	logger = create_logger(level=args.log_level)
	controller = build_controller(runtime_backend=args.runtime, input_backend=args.input, logger=logger)
	controller.run(max_ticks=args.max_ticks, idle_sleep_s=max(0.0, args.idle_sleep))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

