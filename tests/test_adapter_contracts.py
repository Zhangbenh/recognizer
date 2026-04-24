from __future__ import annotations

from pathlib import Path

import pytest

from application.events import EventType
from application.input_mapper import InputMapper
from application.states import State
from domain import MapStatsItem, MapStatsSnapshot
from domain.errors import CloudConfigError, CloudTimeoutError, ConfigError, LabelError, ModelError
from domain.models import RecognitionResult
from domain.release_gate_service import ReleaseGateService
from infrastructure.config.baidu_mapping_repository import BaiduMappingRepository
from infrastructure.config.cloud_config_repository import CloudConfig, CloudConfigRepository
from infrastructure.config.label_repository import LabelRepository
from infrastructure.config.model_manifest_repository import ModelManifestRepository
from infrastructure.config.sampling_config_repository import SamplingConfigRepository
from infrastructure.config.system_config_repository import SystemConfigRepository
from infrastructure.input.keyboard_adapter import KeyboardAdapter
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter


def test_json_storage_adapter_atomic_write_and_corruption_fallback(tmp_path) -> None:
	file_path = tmp_path / "records.json"
	adapter = JsonStorageAdapter(str(file_path), default_value={"regions": {}}, pretty=True)

	assert adapter.read() == {"regions": {}}

	payload = {"regions": {"r1": {"records": {"paddy": {"count": 1}}}}}
	adapter.write(payload)

	assert adapter.exists() is True
	assert adapter.read() == payload
	assert Path(f"{adapter.file_path}.tmp").exists() is False

	adapter.file_path.write_text("{broken json", encoding="utf-8")
	assert adapter.read() == {"regions": {}}


# ── A2: JSON 存储重复写入稳定性（100次写入，无损坏，文件 < 1MB）───────────────

def test_json_storage_100_repeated_writes_no_corruption(tmp_path) -> None:
	"""100 次重复写入，每次读回断言内容一致，最终文件大小 < 1MB（系统说明约束）。"""
	file_path = tmp_path / "stability_records.json"
	default = {"regions": {}}
	adapter = JsonStorageAdapter(str(file_path), default_value=default, pretty=False)

	for i in range(100):
		payload = {
			"regions": {
				f"region_{i % 4}": {
					"records": {
						"paddy": {"count": i + 1, "confidence": 0.9},
						"aloevera": {"count": i, "confidence": 0.85},
					}
				}
			}
		}
		adapter.write(payload)
		read_back = adapter.read()
		assert read_back == payload, f"write-read mismatch at iteration {i}"
		assert not Path(f"{adapter.file_path}.tmp").exists(), f".tmp file leaked at iteration {i}"

	file_size_bytes = adapter.file_path.stat().st_size
	assert file_size_bytes < 1 * 1024 * 1024, (
		f"JSON file size {file_size_bytes} bytes exceeds 1MB limit"
	)


def test_keyboard_adapter_queue_contract() -> None:
	adapter = KeyboardAdapter(enable_stdin_poll=False)
	adapter.push_simulated_event("BTN1_SHORT")
	adapter.push_simulated_event("BTN2_LONG")

	events = adapter.poll_raw_inputs()
	assert [event["event_type"] for event in events] == ["BTN1_SHORT", "BTN2_LONG"]
	assert adapter.poll_raw_inputs() == []


def test_input_mapper_error_confirm_maps_to_retry_press() -> None:
	mapper = InputMapper()

	error_event = mapper.map_raw_input("BTN1_SHORT", State.ERROR)
	assert error_event is not None
	assert error_event.event_type == EventType.RETRY_PRESS
	assert error_event.source == "ErrorPageInputMapping"

	normal_event = mapper.map_raw_input({"event_type": "BTN2_SHORT"}, State.HOME)
	assert normal_event is not None
	assert normal_event.event_type == EventType.NAV_PRESS


def test_config_repositories_contracts_and_release_gate() -> None:
	system_repo = SystemConfigRepository()
	label_repo = LabelRepository()
	manifest_repo = ModelManifestRepository()
	sampling_repo = SamplingConfigRepository()

	assert system_repo.long_press_threshold_ms() == 800
	assert system_repo.capture_debounce_ms() == 100
	assert system_repo.ui_language() == "zh-CN"
	assert system_repo.recognition_strategy() == "cloud_first"
	assert system_repo.cloud_request_timeout_s() == 3.0
	assert system_repo.local_infer_timeout_s() == 1.5
	assert system_repo.cloud_recognition_threshold() == 0.5
	assert system_repo.boot_splash_duration_s() == 3.0
	assert system_repo.get("ui_language") == "zh-CN"
	assert system_repo.get("recognition_strategy") == "cloud_first"
	assert system_repo.get("cloud_request_timeout_s") == 3.0
	assert system_repo.get("local_infer_timeout_s") == 1.5
	assert system_repo.infer_timeout_s() == 4.5
	assert system_repo.display_timeout_s() == 5.0
	assert system_repo.record_timeout_s() == 1.0
	budget = system_repo.performance_budget()
	assert budget["cloud_success_s"] == 3.0
	assert budget["cloud_fallback_s"] == 4.5

	labels = label_repo.index_map()
	assert len(labels) == 30
	assert labels[0]["display_name"] == "芦荟"

	assert manifest_repo.output_classes() == 30
	assert manifest_repo.get_model_file().endswith(".tflite")

	maps = sampling_repo.list_maps()
	assert len(maps) >= 1
	assert str(maps[0]["display_name"] or "").strip()
	assert maps[0]["thumbnail_path"].endswith(".png")
	first_map_id = str(maps[0]["map_id"])
	regions = sampling_repo.list_regions(first_map_id)
	assert len(regions) >= 1
	assert str(regions[0]["display_name"] or "").strip()
	assert regions[0]["thumbnail_path"].endswith(".png")

	release_gate = ReleaseGateService(
		model_manifest_repository=manifest_repo,
		system_config_repository=system_repo,
	)
	assert release_gate.check() is True


def test_cloud_config_and_mapping_repository_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("BAIDU_API_KEY", "config-api-key")
	monkeypatch.setenv("BAIDU_SECRET_KEY", "config-secret-key")
	monkeypatch.setenv("RECOGNIZER_BAIDU_REQUEST_TIMEOUT_S", "3.25")

	cloud_repo = CloudConfigRepository()
	mapping_repo = BaiduMappingRepository()
	config = cloud_repo.load()

	assert config.baidu_api_endpoint.endswith("/rest/2.0/image-classify/v1/plant")
	assert config.baidu_token_endpoint.endswith("/oauth/2.0/token")
	assert config.request_timeout_s == 3.25
	assert config.retry_count == 1
	assert config.api_key == "config-api-key"
	assert config.secret_key == "config-secret-key"
	assert config.api_key_env_name == "BAIDU_API_KEY"
	assert config.secret_key_env_name == "BAIDU_SECRET_KEY"
	assert config.token_cache_file.name == ".baidu_token_cache.json"
	assert mapping_repo.plant_key_for(" 辣椒 ") == "peperchili"
	assert mapping_repo.plant_key_for("不存在的植物") is None


def test_cloud_config_require_credentials_error_mentions_supported_sources() -> None:
	config = CloudConfig(
		version="1.1.0",
		baidu_api_endpoint="https://example.test/plant",
		baidu_token_endpoint="https://example.test/token",
		token_cache_file=Path("cache.json"),
		request_timeout_s=3.0,
		retry_count=1,
		api_key=None,
		secret_key=None,
	)

	with pytest.raises(CloudConfigError, match="api_key / secret_key in config/cloud_config.json"):
		config.require_credentials()


def test_label_repository_invalid_payload_raises_label_error(tmp_path) -> None:
	path = tmp_path / "labels.json"
	path.write_text('{"labels": {"bad": true}}', encoding="utf-8")
	repo = LabelRepository(file_path=str(path))

	with pytest.raises(LabelError):
		repo.load()


def test_model_manifest_missing_file_raises_model_error(tmp_path) -> None:
	repo = ModelManifestRepository(file_path=str(tmp_path / "missing_manifest.json"))

	with pytest.raises(ModelError):
		repo.load()


def test_sampling_config_invalid_maps_raises_config_error(tmp_path) -> None:
	path = tmp_path / "sampling_config.json"
	path.write_text('{"maps": {"bad": true}}', encoding="utf-8")
	repo = SamplingConfigRepository(file_path=str(path))

	with pytest.raises(ConfigError):
		repo.list_maps()


def test_v11_domain_models_support_cloud_metadata_and_map_stats() -> None:
	result = RecognitionResult(
		class_id=18,
		plant_key="cloud:野花",
		plant_name="野花",
		display_name="野花",
		confidence=0.93,
		is_recognized=True,
		source="cloud",
		fallback_used=True,
		raw_label_name="野花",
		catalog_mapped=False,
		top3=[(18, 0.93)],
	)

	assert result.source == "cloud"
	assert result.fallback_used is True
	assert result.raw_label_name == "野花"
	assert result.catalog_mapped is False

	unrecognized = RecognitionResult.unrecognized()
	assert unrecognized.source == "local"
	assert unrecognized.fallback_used is False
	assert unrecognized.raw_label_name is None
	assert unrecognized.catalog_mapped is False

	snapshot = MapStatsSnapshot(
		map_id="map_a",
		map_display_name="地图A",
		total_region_count=4,
		recorded_region_count=2,
		items=[
			MapStatsItem(
				plant_key="paddy",
				display_name="水稻",
				total_count=3,
				covered_region_count=2,
				last_confidence=0.91,
				catalog_mapped=True,
			),
			MapStatsItem(
				plant_key="cloud:野花",
				display_name="野花",
				total_count=2,
				covered_region_count=1,
				last_confidence=0.86,
				catalog_mapped=False,
			),
			MapStatsItem(
				plant_key="banana",
				display_name="香蕉",
				total_count=1,
				covered_region_count=1,
				last_confidence=0.77,
				catalog_mapped=True,
			),
		],
		page_size=2,
	)

	assert snapshot.plant_species_count == 3
	assert snapshot.total_pages == 2
	assert [item.plant_key for item in snapshot.page(0)] == ["paddy", "cloud:野花"]
	assert [item.plant_key for item in snapshot.page(1)] == ["banana"]


def test_cloud_error_types_preserve_retryable_metadata() -> None:
	error = CloudTimeoutError("cloud request timed out", retryable=True)
	error_info = error.to_error_info()

	assert error_info.error_type == "CloudTimeoutError"
	assert error_info.message == "cloud request timed out"
	assert error_info.retryable is True
