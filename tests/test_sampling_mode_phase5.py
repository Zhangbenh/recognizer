from __future__ import annotations

from application.state_context import StateContext
from application.states import State
from domain.errors import DataError
from domain.models import RecognitionResult
from domain.sampling_recorder import SamplingRecorder
from domain.statistics_query_service import StatisticsQueryService
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository
from presentation.pages.map_page import MapPage
from presentation.pages.region_page import RegionPage
from presentation.pages.stats_page import StatsPage
from presentation.view_models import build_view_model


def test_region_stats_repository_round_trip(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)

	repository.save_region_stats("map_a_r1", {"records": {"paddy": {"count": 2}}})

	region = repository.load_region_stats("map_a_r1")
	assert region["records"]["paddy"]["count"] == 2

	payload = repository.load_all()
	assert "map_a_r1" in payload["regions"]


def test_sampling_services_work_with_repository(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	stats_service = StatisticsQueryService(stats_repository=repository)

	result = RecognitionResult(
		class_id=18,
		plant_key="paddy",
		plant_name="paddy",
		display_name="Paddy",
		confidence=0.91,
		is_recognized=True,
		top3=[(18, 0.91), (0, 0.05), (1, 0.04)],
	)

	recorder.record("map_a_r1", result)
	recorder.record("map_a_r1", result)

	snapshot = stats_service.snapshot_for_region("map_a_r1")
	assert snapshot.region_id == "map_a_r1"
	assert len(snapshot.items) == 1
	assert snapshot.items[0].display_name == "Paddy"
	assert snapshot.items[0].count == 2


def test_statistics_sorts_by_display_name_standard(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	stats_service = StatisticsQueryService(stats_repository=repository)

	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=1,
			plant_key="zeta",
			plant_name="zeta",
			display_name="Zeta",
			confidence=0.91,
			is_recognized=True,
			top3=[(1, 0.91)],
		),
	)

	for _ in range(3):
		recorder.record(
			"map_a_r1",
			RecognitionResult(
				class_id=2,
				plant_key="alpha",
				plant_name="alpha",
				display_name="Alpha",
				confidence=0.95,
				is_recognized=True,
				top3=[(2, 0.95)],
			),
		)

	snapshot = stats_service.snapshot_for_region("map_a_r1")
	assert [item.display_name for item in snapshot.items] == ["Alpha", "Zeta"]


def test_sampling_recorder_rejects_invalid_recognized_result(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)

	bad_result = RecognitionResult(
		class_id=7,
		plant_key=None,
		plant_name=None,
		display_name=None,
		confidence=0.88,
		is_recognized=True,
		top3=[(7, 0.88)],
	)

	try:
		recorder.record("map_a_r1", bad_result)
		raise AssertionError("expected DataError for invalid recognized payload")
	except DataError:
		pass


def test_sampling_pages_render_with_view_models() -> None:
	ctx = StateContext(
		mode="sampling",
		available_maps=[
			{"map_id": "map_a", "display_name": "Map A"},
			{"map_id": "map_b", "display_name": "Map B"},
		],
		selected_map_index=1,
		selected_map_id="map_b",
		available_regions=[
			{"region_id": "map_b_r1", "display_name": "Region 1"},
			{"region_id": "map_b_r2", "display_name": "Region 2"},
		],
		selected_region_index=0,
		selected_region_id="map_b_r1",
	)

	map_vm = build_view_model(State.MAP_SELECT, ctx)
	region_vm = build_view_model(State.REGION_SELECT, ctx)

	map_lines = MapPage.render(map_vm)
	region_lines = RegionPage.render(region_vm)

	assert map_vm["selected_map_display_name"] == "Map B"
	assert region_vm["selected_region_display_name"] == "Region 1"
	assert map_lines[0] == "[MapSelect]"
	assert region_lines[0] == "[RegionSelect]"

	# Stats page should render item list in current page.
	from domain.models import StatsItem, StatsSnapshot

	ctx.current_stats_snapshot = StatsSnapshot(
		region_id="map_b_r1",
		items=[
			StatsItem(
				plant_key="paddy",
				plant_name="paddy",
				display_name="Paddy",
				count=3,
				last_confidence=0.88,
				last_seen_at="2026-01-01T00:00:00+00:00",
			)
		],
		page_size=4,
	)

	stats_vm = build_view_model(State.STATS, ctx)
	stats_lines = StatsPage.render(stats_vm)
	assert stats_lines[0] == "[Stats]"
	assert any("Paddy" in line for line in stats_lines)
