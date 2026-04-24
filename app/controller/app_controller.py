"""Application controller that orchestrates loop, input, state machine, and rendering."""

from __future__ import annotations

import json
import logging
import os
import struct
import time
import importlib
from pathlib import Path
from typing import Any, Callable, Optional

from application.events import Event, EventType
from application.input_mapper import InputMapper
from application.state_machine import StateMachine
from application.states import State
from domain.recognition_service import RecognitionService
from presentation.renderer import Renderer
from application.error_policy import ErrorPolicy
from application.state_context import StateContext
from application.state_handlers import (
	BootingHandler,
	CapturedHandler,
	DisplayHandler,
	ErrorHandler,
	HomeHandler,
	InferencingHandler,
	MapSelectHandler,
	MapStatsHandler,
	PreviewHandler,
	RecordingHandler,
	RegionSelectHandler,
	StatsHandler,
)
from domain.release_gate_service import ReleaseGateService
from domain.sampling_recorder import SamplingRecorder
from domain.statistics_query_service import StatisticsQueryService
from infrastructure.cloud.baidu_plant_client import (
	BaiduPlantCandidate,
	BaiduPlantClient,
	BaiduPlantResponse,
)
from infrastructure.camera.base_camera_adapter import BaseCameraAdapter
from infrastructure.camera.picamera2_adapter import Picamera2Adapter
from infrastructure.config.baidu_mapping_repository import BaiduMappingRepository
from infrastructure.config.cloud_config_repository import CloudConfigRepository
from infrastructure.config.label_repository import LabelRepository
from infrastructure.config.model_manifest_repository import ModelManifestRepository
from infrastructure.config.sampling_config_repository import SamplingConfigRepository
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter, InferenceOutput
from infrastructure.inference.tflite_adapter import TFLiteAdapter
from infrastructure.input.gpio_button_adapter import GPIOButtonAdapter
from infrastructure.input.keyboard_adapter import KeyboardAdapter
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository


class AppController:
	"""Runtime composition root for the single-thread loop."""

	def __init__(
		self,
		*,
		state_machine: StateMachine,
		input_adapter,
		input_mapper: InputMapper,
		renderer: Renderer,
		recognition_service: RecognitionService,
		release_gate_service: object | None = None,
		logger: Optional[logging.Logger] = None,
		max_events_per_tick: int = 64,
	) -> None:
		self._state_machine = state_machine
		self._input_adapter = input_adapter
		self._input_mapper = input_mapper
		self._renderer = renderer
		self._recognition_service = recognition_service
		# Keep this attribute for acceptance scripts that inspect controller internals.
		self._release_gate_service = release_gate_service
		self._logger = logger or logging.getLogger("recognizer.controller")
		self._max_events_per_tick = max(1, int(max_events_per_tick))
		self._running = False

	def run(self, *, max_ticks: Optional[int] = None, idle_sleep_s: float = 0.02) -> None:
		tick_count = 0
		self._running = True
		self._state_machine.start()

		try:
			while self._running:
				did_work = self.tick()
				tick_count += 1

				if max_ticks is not None and tick_count >= max_ticks:
					break

				if not did_work and idle_sleep_s > 0:
					time.sleep(idle_sleep_s)
		except KeyboardInterrupt:
			self._logger.info("runtime interrupted by user")
		finally:
			self.stop()

	def tick(self) -> bool:
		did_work = False
		current_state = self._state_machine.current_state

		for raw_input in self._poll_raw_inputs_safe():
			event = self._input_mapper.map_raw_input(raw_input, current_state)
			if event is None:
				continue

			self._prepare_event_before_enqueue(event, current_state)
			self._state_machine.enqueue(event)
			did_work = True

		processed = 0
		while processed < self._max_events_per_tick and self._state_machine.process_next_event():
			processed += 1
			did_work = True

		if processed >= self._max_events_per_tick:
			self._logger.warning("max events per tick reached: %s", self._max_events_per_tick)

		render_state = self._state_machine.current_state
		self._refresh_preview_frame(render_state)
		self._renderer.render(render_state, self._state_machine.context)
		return did_work

	def request_stop(self) -> None:
		self._running = False

	def stop(self) -> None:
		self._running = False

		try:
			self._input_adapter.close()
		except Exception:
			self._logger.exception("failed to close input adapter")

		try:
			self._recognition_service.shutdown()
		except Exception:
			self._logger.exception("failed to shutdown recognition service")

		try:
			self._renderer.close()
		except Exception:
			self._logger.exception("failed to close renderer")

	def _poll_raw_inputs_safe(self):
		try:
			return self._input_adapter.poll_raw_inputs()
		except Exception as exc:
			self._state_machine.context.set_error(exc)
			self._state_machine.enqueue(
				Event.system_error(
					message="input_poll_failed",
					source="AppController",
					details={"reason": str(exc)},
				)
			)
			return []

	def _prepare_event_before_enqueue(self, event: Event, current_state: State) -> None:
		if current_state == State.PREVIEW and event.event_type == EventType.CONFIRM_PRESS:
			self._attach_capture_frame(event)

	def _attach_capture_frame(self, event: Event) -> None:
		try:
			frame = self._recognition_service.capture_frame()
		except Exception as exc:
			event.payload["capture_error"] = str(exc)
			self._state_machine.context.set_error(exc)
			return

		self._state_machine.context.preview_frame = frame
		event.payload["frame"] = frame

	def _refresh_preview_frame(self, current_state: State) -> None:
		if not self._renderer.needs_live_preview_frames:
			return

		ctx = self._state_machine.context

		if current_state == State.PREVIEW:
			try:
				ctx.preview_frame = self._recognition_service.capture_frame()
			except Exception as exc:
				# Keep existing UI fallback behavior without forcing state transitions.
				ctx.set_error(exc)
				ctx.preview_error_flash_pending = True
			return

		if current_state in {State.CAPTURED, State.INFERENCING, State.DISPLAY, State.RECORDING}:
			if ctx.last_captured_frame is not None:
				ctx.preview_frame = ctx.last_captured_frame
			return

		ctx.preview_frame = None


class _MockCameraAdapter(BaseCameraAdapter):
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
		return {"mock": "frame"}

	def close(self) -> None:
		self._started = False


class _MockInferenceAdapter(BaseInferenceAdapter):
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


class _MockBaiduPlantClient:
	"""Desktop-safe cloud client stub for mock runtime wiring."""

	def recognize_image_bytes(self, image_bytes: bytes, *, baike_num: int = 0) -> BaiduPlantResponse:
		_ = image_bytes, baike_num
		return BaiduPlantResponse(
			log_id=0,
			candidates=[BaiduPlantCandidate(name="芦荟", score=0.96)],
			raw_payload={"result": [{"name": "芦荟", "score": 0.96}]},
		)


def _env_int(name: str, default: int) -> int:
	raw = os.getenv(name, "").strip()
	if not raw:
		return default
	try:
		return int(raw)
	except ValueError:
		return default


def _env_float(name: str, default: float) -> float:
	raw = os.getenv(name, "").strip()
	if not raw:
		return default
	try:
		return float(raw)
	except ValueError:
		return default


def _env_bool(name: str, default: bool) -> bool:
	raw = os.getenv(name, "").strip().lower()
	if not raw:
		return default
	return raw not in {"0", "false", "no", "off"}


def _default_camera_options() -> dict[str, Any]:
	screen_width = _env_int("RECOGNIZER_SCREEN_WIDTH", 480)
	screen_height = _env_int("RECOGNIZER_SCREEN_HEIGHT", 800)
	portrait_layout = screen_height >= screen_width
	return {
		"width": _env_int("RECOGNIZER_CAMERA_WIDTH", 800 if portrait_layout else 480),
		"height": _env_int("RECOGNIZER_CAMERA_HEIGHT", 480 if portrait_layout else 320),
		"rotation": _env_int("RECOGNIZER_CAMERA_ROTATION", 270 if portrait_layout else 180),
		"swap_red_blue": _env_bool("RECOGNIZER_CAMERA_SWAP_RED_BLUE", True),
		"warmup_seconds": _env_float("RECOGNIZER_CAMERA_WARMUP_S", 0.5),
	}


def _build_runtime_adapters(
	*, runtime_backend: str, expected_output_classes: int
) -> tuple[BaseCameraAdapter, BaseInferenceAdapter]:
	if runtime_backend == "mock":
		return _MockCameraAdapter(), _MockInferenceAdapter(expected_output_classes=expected_output_classes)

	camera_adapter = Picamera2Adapter(**_default_camera_options())
	inference_adapter = TFLiteAdapter(expected_output_classes=expected_output_classes)
	return camera_adapter, inference_adapter


def _build_cloud_client(*, runtime_backend: str, config_repository: CloudConfigRepository):
	if runtime_backend == "mock":
		return _MockBaiduPlantClient()
	return BaiduPlantClient(config_repository=config_repository)


def _encode_frame_for_cloud(frame: Any) -> bytes:
	if frame is None:
		raise ValueError("frame is empty")

	if isinstance(frame, (bytes, bytearray, memoryview)):
		return bytes(frame)

	if isinstance(frame, (dict, list, tuple, str, int, float, bool)):
		return json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")

	try:
		np = importlib.import_module("numpy")
	except Exception:
		np = None

	if np is not None and isinstance(frame, np.ndarray):
		array = frame
		if array.ndim == 4 and array.shape[0] == 1:
			array = array[0]
		if array.ndim != 3 or array.shape[2] != 3:
			raise ValueError("cloud frame encoder expects RGB image shape (H, W, 3)")
		return _encode_rgb_array_to_bmp_bytes(array)

	raise TypeError(f"unsupported frame type for cloud encoding: {type(frame).__name__}")


def _encode_rgb_array_to_bmp_bytes(array: Any) -> bytes:
	rgb = array.astype("uint8", copy=False)
	if rgb.ndim != 3 or rgb.shape[2] != 3:
		raise ValueError("cloud bmp encoder expects RGB image shape (H, W, 3)")

	height, width, _channels = rgb.shape
	row_stride = ((width * 3 + 3) // 4) * 4
	padding = row_stride - width * 3
	padding_bytes = b"\x00" * padding
	rows: list[bytes] = []
	for row in rgb[::-1]:
		bgr_row = row[:, [2, 1, 0]].tobytes()
		rows.append(bgr_row + padding_bytes)
	pixel_data = b"".join(rows)

	file_header_size = 14
	info_header_size = 40
	pixel_offset = file_header_size + info_header_size
	file_size = pixel_offset + len(pixel_data)

	file_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, pixel_offset)
	info_header = struct.pack(
		"<IIIHHIIIIII",
		info_header_size,
		width,
		height,
		1,
		24,
		0,
		len(pixel_data),
		2835,
		2835,
		0,
		0,
	)
	return file_header + info_header + pixel_data


def _build_input_adapter(*, input_backend: str, system_config: SystemConfigRepository):
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


def build_app_controller(
	*,
	runtime_backend: str,
	input_backend: str,
	ui_backend: str = "text",
	logger: logging.Logger,
	storage_adapter_factory: Callable[..., Any] = JsonStorageAdapter,
	label_repository: LabelRepository | None = None,
	model_manifest_repository: ModelManifestRepository | None = None,
	sampling_config_repository: SamplingConfigRepository | None = None,
	system_config_repository: SystemConfigRepository | None = None,
	camera_adapter: BaseCameraAdapter | None = None,
	inference_adapter: BaseInferenceAdapter | None = None,
	cloud_config_repository: CloudConfigRepository | None = None,
	baidu_mapping_repository: BaiduMappingRepository | None = None,
	baidu_plant_client: Any | None = None,
	frame_encoder: Callable[[Any], bytes] | None = None,
) -> AppController:
	repo_root = Path(__file__).resolve().parents[2]
	data_file = repo_root / "data" / "sampling_records.json"

	label_repository = label_repository or LabelRepository()
	model_manifest_repository = model_manifest_repository or ModelManifestRepository()
	sampling_config_repository = sampling_config_repository or SamplingConfigRepository()
	system_config_repository = system_config_repository or SystemConfigRepository()
	cloud_config_repository = cloud_config_repository or CloudConfigRepository()
	baidu_mapping_repository = baidu_mapping_repository or BaiduMappingRepository()
	storage_adapter = storage_adapter_factory(str(data_file), default_value={"regions": {}}, pretty=True)
	stats_repository = RegionStatsRepository(storage_adapter=storage_adapter)

	expected_output_classes = model_manifest_repository.output_classes()
	default_camera_adapter, default_inference_adapter = _build_runtime_adapters(
		runtime_backend=runtime_backend,
		expected_output_classes=expected_output_classes,
	)
	camera_adapter = camera_adapter or default_camera_adapter
	inference_adapter = inference_adapter or default_inference_adapter
	baidu_plant_client = baidu_plant_client or _build_cloud_client(
		runtime_backend=runtime_backend,
		config_repository=cloud_config_repository,
	)
	frame_encoder = frame_encoder or _encode_frame_for_cloud
	input_adapter = _build_input_adapter(input_backend=input_backend, system_config=system_config_repository)

	recognition_service = RecognitionService(
		camera_adapter=camera_adapter,
		inference_adapter=inference_adapter,
		label_repository=label_repository,
		model_manifest_repository=model_manifest_repository,
		system_config_repository=system_config_repository,
		baidu_plant_client=baidu_plant_client,
		baidu_mapping_repository=baidu_mapping_repository,
		frame_encoder=frame_encoder,
		logger=logger,
	)
	release_gate_service = ReleaseGateService(
		model_manifest_repository=model_manifest_repository,
		system_config_repository=system_config_repository,
	)
	sampling_recorder = SamplingRecorder(stats_repository=stats_repository)
	statistics_query_service = StatisticsQueryService(stats_repository=stats_repository)
	error_policy = ErrorPolicy()

	def _retry_boot() -> None:
		release_gate_service.ensure_pass()
		recognition_service.boot()

	handlers = {
		State.BOOTING: BootingHandler(
			release_gate_service=release_gate_service,
			recognition_service=recognition_service,
			sampling_config_repository=sampling_config_repository,
		),
		State.HOME: HomeHandler(),
		State.MAP_SELECT: MapSelectHandler(sampling_config_repository=sampling_config_repository),
		State.MAP_STATS: MapStatsHandler(statistics_query_service=statistics_query_service),
		State.REGION_SELECT: RegionSelectHandler(sampling_config_repository=sampling_config_repository),
		State.PREVIEW: PreviewHandler(),
		State.CAPTURED: CapturedHandler(),
		State.INFERENCING: InferencingHandler(recognition_service=recognition_service),
		State.DISPLAY: DisplayHandler(),
		State.RECORDING: RecordingHandler(sampling_recorder=sampling_recorder),
		State.STATS: StatsHandler(statistics_query_service=statistics_query_service),
		State.ERROR: ErrorHandler(retry_executor=_retry_boot, error_policy=error_policy),
	}

	state_machine = StateMachine(context=StateContext(), handlers=handlers)
	input_mapper = InputMapper()
	renderer = Renderer(logger=logger, ui_backend=ui_backend)

	return AppController(
		state_machine=state_machine,
		input_adapter=input_adapter,
		input_mapper=input_mapper,
		renderer=renderer,
		recognition_service=recognition_service,
		release_gate_service=release_gate_service,
		logger=logger,
	)

