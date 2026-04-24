from __future__ import annotations

import logging
from pathlib import Path

import pytest

from domain.errors import CloudTimeoutError
from domain.recognition_service import RecognitionService
from domain.sampling_recorder import SamplingRecorder
from infrastructure.cloud.baidu_plant_client import BaiduPlantCandidate, BaiduPlantResponse
from infrastructure.inference.base_inference_adapter import InferenceOutput
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository


class _CameraStub:
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
		return {"frame": "mock"}

	def close(self) -> None:
		self._started = False


class _InferenceStub:
	def __init__(self, *, output: InferenceOutput | None = None) -> None:
		self._output = output or InferenceOutput(class_id=18, confidence=0.92, top3=[(18, 0.92)])
		self._loaded = False
		self.infer_calls = 0

	@property
	def is_loaded(self) -> bool:
		return self._loaded

	def load_model(self, _model_path: str) -> None:
		self._loaded = True

	def infer(self, _image) -> InferenceOutput:
		self.infer_calls += 1
		return self._output

	def close(self) -> None:
		self._loaded = False


class _LabelRepoStub:
	def index_map(self) -> dict[int, dict[str, object]]:
		return {
			1: {"index": 1, "plant_key": "banana", "plant_name": "banana", "display_name": "香蕉"},
			18: {"index": 18, "plant_key": "paddy", "plant_name": "paddy", "display_name": "水稻"},
		}


class _ModelManifestRepoStub:
	def __init__(self, model_path: Path) -> None:
		self._model_path = model_path

	def resolve_model_path(self) -> Path:
		return self._model_path


class _SystemConfigRepoStub:
	def __init__(self, *, strategy: str = "cloud_first", threshold: float = 0.6, cloud_threshold: float | None = None) -> None:
		self._strategy = strategy
		self._threshold = threshold
		self._cloud_threshold = threshold if cloud_threshold is None else cloud_threshold

	def recognition_threshold(self) -> float:
		return self._threshold

	def cloud_recognition_threshold(self) -> float:
		return self._cloud_threshold

	def recognition_strategy(self) -> str:
		return self._strategy


class _CloudClientStub:
	def __init__(self, response: BaiduPlantResponse | Exception) -> None:
		self._response = response
		self.calls: list[bytes] = []

	def recognize_image_bytes(self, image_bytes: bytes) -> BaiduPlantResponse:
		self.calls.append(image_bytes)
		if isinstance(self._response, Exception):
			raise self._response
		return self._response


class _MappingRepoStub:
	def __init__(self, mappings: dict[str, str] | None = None) -> None:
		self._mappings = mappings or {}

	def plant_key_for(self, baidu_name: str) -> str | None:
		return self._mappings.get(baidu_name.strip())


def _build_service(
	*,
	tmp_path: Path,
	inference_output: InferenceOutput,
	cloud_response: BaiduPlantResponse | Exception,
	mappings: dict[str, str] | None = None,
	local_threshold: float = 0.6,
	cloud_threshold: float | None = None,
) -> tuple[RecognitionService, _InferenceStub, _CloudClientStub]:
	model_path = tmp_path / "model.tflite"
	model_path.write_bytes(b"fake-model")
	inference = _InferenceStub(output=inference_output)
	cloud_client = _CloudClientStub(cloud_response)
	service = RecognitionService(
		camera_adapter=_CameraStub(),
		inference_adapter=inference,
		label_repository=_LabelRepoStub(),
		model_manifest_repository=_ModelManifestRepoStub(model_path),
		system_config_repository=_SystemConfigRepoStub(threshold=local_threshold, cloud_threshold=cloud_threshold),
		baidu_plant_client=cloud_client,
		baidu_mapping_repository=_MappingRepoStub(mappings),
		frame_encoder=lambda frame: b"encoded-frame:" + str(frame).encode("utf-8"),
		logger=logging.getLogger("recognizer.tests.cloud-first"),
	)
	service.boot()
	return service, inference, cloud_client


def test_recognition_service_uses_cloud_mapped_result_before_local(tmp_path: Path) -> None:
	service, inference, cloud_client = _build_service(
		tmp_path=tmp_path,
		inference_output=InferenceOutput(class_id=18, confidence=0.91, top3=[(18, 0.91)]),
		cloud_response=BaiduPlantResponse(
			log_id=1,
			candidates=[BaiduPlantCandidate(name="香蕉", score=0.98)],
			raw_payload={"result": [{"name": "香蕉", "score": 0.98}]},
		),
		mappings={"香蕉": "banana"},
	)

	result = service.recognize({"frame": "mapped"})

	assert result.is_recognized is True
	assert result.source == "cloud"
	assert result.fallback_used is False
	assert result.class_id == 1
	assert result.plant_key == "banana"
	assert result.plant_name == "banana"
	assert result.display_name == "香蕉"
	assert result.raw_label_name == "香蕉"
	assert result.catalog_mapped is True
	assert inference.infer_calls == 0
	assert len(cloud_client.calls) == 1


def test_recognition_service_generates_cloud_extension_key_and_recorder_persists_it(tmp_path: Path) -> None:
	service, inference, _cloud_client = _build_service(
		tmp_path=tmp_path,
		inference_output=InferenceOutput(class_id=18, confidence=0.91, top3=[(18, 0.91)]),
		cloud_response=BaiduPlantResponse(
			log_id=2,
			candidates=[BaiduPlantCandidate(name="野花", score=0.93)],
			raw_payload={"result": [{"name": "野花", "score": 0.93}]},
		),
	)

	result = service.recognize({"frame": "extension"})

	assert result.is_recognized is True
	assert result.source == "cloud"
	assert result.fallback_used is False
	assert result.plant_key == "cloud:野花"
	assert result.plant_name == "野花"
	assert result.display_name == "野花"
	assert result.raw_label_name == "野花"
	assert result.catalog_mapped is False
	assert inference.infer_calls == 0

	storage = JsonStorageAdapter(str(tmp_path / "sampling_records.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	recorder.record("map_a_r1", result)
	records = recorder.region_records("map_a_r1")

	assert list(records) == ["cloud:野花"]
	assert records["cloud:野花"]["display_name"] == "野花"
	assert records["cloud:野花"]["plant_name"] == "野花"
	assert records["cloud:野花"]["count"] == 1


def test_recognition_service_uses_cloud_specific_threshold_before_local(tmp_path: Path) -> None:
	service, inference, cloud_client = _build_service(
		tmp_path=tmp_path,
		inference_output=InferenceOutput(class_id=18, confidence=0.91, top3=[(18, 0.91)]),
		cloud_response=BaiduPlantResponse(
			log_id=3,
			candidates=[BaiduPlantCandidate(name="香蕉", score=0.556)],
			raw_payload={"result": [{"name": "香蕉", "score": 0.556}]},
		),
		mappings={"香蕉": "banana"},
		local_threshold=0.6,
		cloud_threshold=0.5,
	)

	result = service.recognize({"frame": "cloud-threshold"})

	assert result.is_recognized is True
	assert result.source == "cloud"
	assert result.fallback_used is False
	assert result.class_id == 1
	assert result.plant_key == "banana"
	assert result.display_name == "香蕉"
	assert result.confidence == pytest.approx(0.556)
	assert service.threshold == pytest.approx(0.6)
	assert service.cloud_threshold == pytest.approx(0.5)
	assert inference.infer_calls == 0
	assert len(cloud_client.calls) == 1


def test_recognition_service_falls_back_to_local_when_cloud_fails(tmp_path: Path) -> None:
	service, inference, _cloud_client = _build_service(
		tmp_path=tmp_path,
		inference_output=InferenceOutput(class_id=18, confidence=0.91, top3=[(18, 0.91)]),
		cloud_response=CloudTimeoutError("cloud request timed out", retryable=True),
	)

	result = service.recognize({"frame": "fallback"})

	assert result.is_recognized is True
	assert result.source == "local"
	assert result.fallback_used is True
	assert result.plant_key == "paddy"
	assert result.display_name == "水稻"
	assert result.catalog_mapped is True
	assert inference.infer_calls == 1


def test_recognition_service_returns_unrecognized_when_cloud_and_local_both_fail(tmp_path: Path) -> None:
	service, inference, _cloud_client = _build_service(
		tmp_path=tmp_path,
		inference_output=InferenceOutput(class_id=18, confidence=0.12, top3=[(18, 0.12)]),
		cloud_response=CloudTimeoutError("cloud request timed out", retryable=True),
	)

	result = service.recognize({"frame": "all-failed"})

	assert result.is_recognized is False
	assert result.source == "local"
	assert result.fallback_used is True
	assert result.plant_key is None
	assert result.display_name is None
	assert result.catalog_mapped is False
	assert result.confidence == pytest.approx(0.12)
	assert inference.infer_calls == 1