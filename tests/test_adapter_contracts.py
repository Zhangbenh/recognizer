from __future__ import annotations

from pathlib import Path

import pytest

from application.events import EventType
from application.input_mapper import InputMapper
from application.states import State
from domain.errors import ConfigError, LabelError, ModelError
from domain.release_gate_service import ReleaseGateService
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
	assert system_repo.capture_debounce_ms() == 300
	assert system_repo.infer_timeout_s() == 3.0
	assert system_repo.display_timeout_s() == 5.0
	assert system_repo.record_timeout_s() == 1.0

	labels = label_repo.index_map()
	assert len(labels) == 30
	assert labels[0]["display_name"] == "Aloe Vera"

	assert manifest_repo.output_classes() == 30
	assert manifest_repo.get_model_file().endswith(".tflite")

	maps = sampling_repo.list_maps()
	assert len(maps) >= 1
	first_map_id = str(maps[0]["map_id"])
	regions = sampling_repo.list_regions(first_map_id)
	assert len(regions) >= 1

	release_gate = ReleaseGateService(
		model_manifest_repository=manifest_repo,
		system_config_repository=system_repo,
	)
	assert release_gate.check() is True


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
