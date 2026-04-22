"""Domain service that coordinates camera capture and model inference."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from domain.errors import CameraError, InferenceError, LabelError, ModelError
from domain.models import RecognitionResult
from domain.rules import is_recognized
from infrastructure.camera.base_camera_adapter import BaseCameraAdapter
from infrastructure.config.label_repository import LabelRepository
from infrastructure.config.model_manifest_repository import ModelManifestRepository
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter


class RecognitionService:
	"""High-level recognition orchestration.

	This service intentionally keeps side effects localized so state handlers can
	call one method and receive normalized domain models.
	"""

	def __init__(
		self,
		*,
		camera_adapter: BaseCameraAdapter,
		inference_adapter: BaseInferenceAdapter,
		label_repository: LabelRepository,
		model_manifest_repository: ModelManifestRepository,
		system_config_repository: SystemConfigRepository,
		logger: Optional[logging.Logger] = None,
	) -> None:
		self._camera_adapter = camera_adapter
		self._inference_adapter = inference_adapter
		self._label_repository = label_repository
		self._model_manifest_repository = model_manifest_repository
		self._system_config_repository = system_config_repository
		self._logger = logger or logging.getLogger("recognizer.domain.recognition")

		self._threshold = 0.6
		self._label_index: dict[int, dict[str, Any]] = {}
		self._booted = False

	@property
	def is_ready(self) -> bool:
		return self._booted and self._inference_adapter.is_loaded and self._camera_adapter.is_started

	@property
	def threshold(self) -> float:
		return self._threshold

	def boot(self) -> None:
		self._threshold = self._system_config_repository.recognition_threshold()
		self._label_index = self._label_repository.index_map()
		if not self._label_index:
			raise LabelError("labels are empty", retryable=False)

		model_path = self._model_manifest_repository.resolve_model_path()
		if not model_path.exists():
			raise ModelError(f"model file not found: {model_path}", retryable=False)

		self._load_model(model_path)
		self._start_camera()
		self._booted = True
		self._logger.info("recognition service booted: model=%s threshold=%.3f", model_path, self._threshold)

	def shutdown(self) -> None:
		self._booted = False
		try:
			self._camera_adapter.stop()
		except Exception:
			self._logger.exception("camera stop failed during shutdown")
		finally:
			try:
				self._camera_adapter.close()
			except Exception:
				self._logger.exception("camera close failed during shutdown")

		try:
			self._inference_adapter.close()
		except Exception:
			self._logger.exception("inference close failed during shutdown")

	def capture_frame(self):
		if not self._camera_adapter.is_started:
			self._start_camera()
		try:
			return self._camera_adapter.capture_frame()
		except CameraError:
			raise
		except Exception as exc:
			raise CameraError(f"capture failed: {exc}", retryable=True) from exc

	def recognize(self, frame: Any) -> RecognitionResult:
		if frame is None:
			raise InferenceError("cannot infer from empty frame", retryable=True)

		if not self._inference_adapter.is_loaded:
			raise InferenceError("model is not loaded", retryable=False)

		try:
			output = self._inference_adapter.infer(frame)
		except InferenceError:
			raise
		except Exception as exc:
			raise InferenceError(f"inference failed: {exc}", retryable=True) from exc

		label = self._label_index.get(output.class_id)
		recognized = bool(label) and is_recognized(output.confidence, self._threshold)

		if recognized and label is not None:
			plant_key = str(label.get("plant_key") or label.get("plant_name") or "").strip()
			if not plant_key:
				self._logger.warning(
					"recognized label missing plant key, fallback to unrecognized: class_id=%s",
					output.class_id,
				)
				recognized = False
				plant_key = None
				plant_name = None
				display_name = None
			else:
				plant_name = str(label.get("plant_name") or plant_key).strip()
				display_name = str(label.get("display_name") or plant_name).strip()
		else:
			plant_key = None
			plant_name = None
			display_name = None

		return RecognitionResult(
			class_id=output.class_id,
			plant_key=plant_key,
			plant_name=plant_name,
			display_name=display_name,
			confidence=output.confidence,
			is_recognized=recognized,
			source="local",
			fallback_used=False,
			raw_label_name=plant_name,
			catalog_mapped=recognized,
			top3=list(output.top3),
		)

	def capture_and_recognize(self) -> tuple[Any, RecognitionResult]:
		frame = self.capture_frame()
		result = self.recognize(frame)
		return frame, result

	def _load_model(self, model_path: Path) -> None:
		try:
			self._inference_adapter.load_model(str(model_path))
		except ModelError:
			raise
		except Exception as exc:
			raise ModelError(f"failed to load model: {exc}", retryable=False) from exc

	def _start_camera(self) -> None:
		try:
			self._camera_adapter.start()
		except CameraError:
			raise
		except Exception as exc:
			raise CameraError(f"failed to start camera: {exc}", retryable=True) from exc

