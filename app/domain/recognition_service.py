"""Domain service that coordinates camera capture and model inference."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable, Optional

from domain.errors import CameraError, InferenceError, LabelError, ModelError
from domain.models import RecognitionResult
from domain.rules import is_recognized
from infrastructure.camera.base_camera_adapter import BaseCameraAdapter
from infrastructure.cloud.baidu_plant_client import BaiduPlantClient, BaiduPlantResponse
from infrastructure.config.baidu_mapping_repository import BaiduMappingRepository
from infrastructure.config.label_repository import LabelRepository
from infrastructure.config.model_manifest_repository import ModelManifestRepository
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter, InferenceOutput


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
		baidu_plant_client: BaiduPlantClient | None = None,
		baidu_mapping_repository: BaiduMappingRepository | None = None,
		frame_encoder: Callable[[Any], bytes] | None = None,
		logger: Optional[logging.Logger] = None,
	) -> None:
		self._camera_adapter = camera_adapter
		self._inference_adapter = inference_adapter
		self._label_repository = label_repository
		self._model_manifest_repository = model_manifest_repository
		self._system_config_repository = system_config_repository
		self._baidu_plant_client = baidu_plant_client
		self._baidu_mapping_repository = baidu_mapping_repository
		self._frame_encoder = frame_encoder
		self._logger = logger or logging.getLogger("recognizer.domain.recognition")

		self._threshold = 0.6
		self._label_index: dict[int, dict[str, Any]] = {}
		self._label_by_plant_key: dict[str, dict[str, Any]] = {}
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
		self._label_by_plant_key = self._build_label_key_index(self._label_index)

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

		if self._should_try_cloud():
			cloud_result = self._try_cloud_recognition(frame)
			if cloud_result is not None:
				return cloud_result
			return self._recognize_local(frame, fallback_used=True)

		return self._recognize_local(frame, fallback_used=False)

	def _recognize_local(self, frame: Any, *, fallback_used: bool) -> RecognitionResult:
		if not self._inference_adapter.is_loaded:
			raise InferenceError("model is not loaded", retryable=False)

		try:
			output = self._inference_adapter.infer(frame)
		except InferenceError:
			raise
		except Exception as exc:
			raise InferenceError(f"inference failed: {exc}", retryable=True) from exc
		return self._build_local_result(output, fallback_used=fallback_used)

	def _build_local_result(self, output: InferenceOutput, *, fallback_used: bool) -> RecognitionResult:
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
			fallback_used=fallback_used,
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

	def _should_try_cloud(self) -> bool:
		strategy = str(self._system_config_repository.recognition_strategy()).strip().lower()
		return (
			strategy == "cloud_first"
			and self._baidu_plant_client is not None
			and self._frame_encoder is not None
		)

	def _try_cloud_recognition(self, frame: Any) -> RecognitionResult | None:
		try:
			assert self._frame_encoder is not None
			image_bytes = self._frame_encoder(frame)
			if not image_bytes:
				self._logger.info("cloud recognition skipped because encoded frame is empty")
				return None
			response = self._baidu_plant_client.recognize_image_bytes(image_bytes)
		except Exception as exc:
			self._logger.warning("cloud recognition failed, fallback to local: %s", exc)
			return None

		return self._build_cloud_result(response)

	def _build_cloud_result(self, response: BaiduPlantResponse) -> RecognitionResult | None:
		if not response.candidates:
			self._logger.info("cloud recognition returned no candidates, fallback to local")
			return None

		candidate = max(response.candidates, key=lambda item: item.score)
		if not is_recognized(candidate.score, self._threshold):
			self._logger.info(
				"cloud candidate below threshold, fallback to local: name=%s score=%.4f threshold=%.4f",
				candidate.name,
				candidate.score,
				self._threshold,
			)
			return None

		raw_name = self._normalize_cloud_name(candidate.name)
		if not raw_name:
			self._logger.info("cloud recognition returned empty or invalid name, fallback to local")
			return None

		mapped_plant_key = self._lookup_mapped_plant_key(raw_name)
		if mapped_plant_key:
			label = self._label_by_plant_key.get(mapped_plant_key)
			if label is None:
				self._logger.warning(
					"baidu mapping points to unknown local plant_key, fallback to local: raw_name=%s plant_key=%s",
					raw_name,
					mapped_plant_key,
				)
				return None

			class_id_raw = label.get("index")
			class_id = class_id_raw if isinstance(class_id_raw, int) else None
			plant_name = str(label.get("plant_name") or mapped_plant_key).strip() or mapped_plant_key
			display_name = str(label.get("display_name") or raw_name or plant_name).strip() or raw_name
			top3 = [(class_id, candidate.score)] if class_id is not None else []
			return RecognitionResult(
				class_id=class_id,
				plant_key=mapped_plant_key,
				plant_name=plant_name,
				display_name=display_name,
				confidence=candidate.score,
				is_recognized=True,
				source="cloud",
				fallback_used=False,
				raw_label_name=raw_name,
				catalog_mapped=True,
				top3=top3,
			)

		cloud_plant_key = self._build_cloud_plant_key(raw_name)
		if not cloud_plant_key:
			self._logger.warning("cloud plant key normalization failed, fallback to local: raw_name=%s", raw_name)
			return None

		return RecognitionResult(
			class_id=None,
			plant_key=cloud_plant_key,
			plant_name=raw_name,
			display_name=raw_name,
			confidence=candidate.score,
			is_recognized=True,
			source="cloud",
			fallback_used=False,
			raw_label_name=raw_name,
			catalog_mapped=False,
			top3=[],
		)

	def _lookup_mapped_plant_key(self, raw_name: str) -> str | None:
		if self._baidu_mapping_repository is None:
			return None
		try:
			mapped_plant_key = self._baidu_mapping_repository.plant_key_for(raw_name)
		except Exception as exc:
			self._logger.warning("baidu mapping lookup failed, fallback to local: %s", exc)
			return None
		if mapped_plant_key is None:
			return None
		mapped = str(mapped_plant_key).strip()
		return mapped or None

	def _build_label_key_index(self, label_index: dict[int, dict[str, Any]]) -> dict[str, dict[str, Any]]:
		result: dict[str, dict[str, Any]] = {}
		for label in label_index.values():
			plant_key = str(label.get("plant_key") or label.get("plant_name") or "").strip()
			if plant_key:
				result[plant_key] = label
		return result

	def _build_cloud_plant_key(self, raw_name: str) -> str | None:
		normalized_name = self._normalize_cloud_name(raw_name)
		if not normalized_name:
			return None

		token = []
		for char in normalized_name:
			if char.isalnum():
				token.append(char.lower())
			elif char in {" ", "-", "_"}:
				token.append("-")

		stable_token = re.sub(r"-+", "-", "".join(token)).strip("-")
		if not stable_token:
			return None
		if stable_token == normalized_name:
			return f"cloud:{stable_token}"

		digest = hashlib.sha1(normalized_name.encode("utf-8")).hexdigest()[:8]
		return f"cloud:{stable_token}-{digest}"

	def _normalize_cloud_name(self, raw_name: str | None) -> str | None:
		if raw_name is None:
			return None
		normalized = unicodedata.normalize("NFKC", str(raw_name)).strip()
		normalized = re.sub(r"\s+", " ", normalized)
		return normalized or None

