from __future__ import annotations

from application.state_context import StateContext
from application.states import State
from domain.errors import DataError
from domain.models import ErrorInfo
from domain.models import RecognitionResult
from domain.sampling_recorder import SamplingRecorder
from domain.statistics_query_service import StatisticsQueryService
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter
from infrastructure.storage.region_stats_repository import RegionStatsRepository
from presentation.pages.booting_page import BootingPage
from presentation.pages.error_page import ErrorPage
from presentation.pages.home_page import HomePage
from presentation.pages.inferencing_overlay import InferencingOverlay
from presentation.pages.map_page import MapPage
from presentation.pages.map_stats_page import MapStatsPage
from presentation.pages.preview_page import PreviewPage
from presentation.pages.region_page import RegionPage
from presentation.pages.stats_page import StatsPage
from presentation.renderer import Renderer
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


def test_statistics_sort_local_catalog_before_cloud_and_by_label_index(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	stats_service = StatisticsQueryService(stats_repository=repository)

	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=18,
			plant_key="paddy",
			plant_name="paddy",
			display_name="水稻",
			confidence=0.91,
			is_recognized=True,
			top3=[(18, 0.91)],
		),
	)

	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=1,
			plant_key="banana",
			plant_name="banana",
			display_name="香蕉",
			confidence=0.95,
			is_recognized=True,
			top3=[(1, 0.95)],
		),
	)

	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=None,
			plant_key="cloud:wildflower",
			plant_name="wildflower",
			display_name="野花",
			confidence=0.82,
			is_recognized=True,
			source="cloud",
			catalog_mapped=False,
			top3=[],
		),
	)

	snapshot = stats_service.snapshot_for_region("map_a_r1")
	assert [item.plant_key for item in snapshot.items] == ["banana", "paddy", "cloud:wildflower"]


def test_map_statistics_aggregate_records_for_whole_map(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	stats_service = StatisticsQueryService(stats_repository=repository)

	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=1,
			plant_key="banana",
			plant_name="banana",
			display_name="香蕉",
			confidence=0.61,
			is_recognized=True,
			top3=[(1, 0.61)],
		),
	)
	recorder.record(
		"map_a_r1",
		RecognitionResult(
			class_id=1,
			plant_key="banana",
			plant_name="banana",
			display_name="香蕉",
			confidence=0.66,
			is_recognized=True,
			top3=[(1, 0.66)],
		),
	)
	recorder.record(
		"map_a_r2",
		RecognitionResult(
			class_id=1,
			plant_key="banana",
			plant_name="banana",
			display_name="香蕉",
			confidence=0.92,
			is_recognized=True,
			top3=[(1, 0.92)],
		),
	)
	recorder.record(
		"map_a_r2",
		RecognitionResult(
			class_id=None,
			plant_key="cloud:wildflower",
			plant_name="wildflower",
			display_name="野花",
			confidence=0.88,
			is_recognized=True,
			source="cloud",
			catalog_mapped=False,
			top3=[],
		),
	)

	snapshot = stats_service.snapshot_for_map("map_a")

	assert snapshot.map_id == "map_a"
	assert snapshot.map_display_name == "地图A"
	assert snapshot.total_region_count == 4
	assert snapshot.recorded_region_count == 2
	assert snapshot.plant_species_count == 2
	assert [item.plant_key for item in snapshot.items] == ["banana", "cloud:wildflower"]
	assert snapshot.items[0].total_count == 3
	assert snapshot.items[0].covered_region_count == 2
	assert snapshot.items[0].covered_region_names == ["区域1", "区域2"]
	assert snapshot.items[0].last_confidence == 0.92
	assert snapshot.items[0].catalog_mapped is True
	assert snapshot.items[1].total_count == 1
	assert snapshot.items[1].covered_region_count == 1
	assert snapshot.items[1].covered_region_names == ["区域2"]
	assert snapshot.items[1].catalog_mapped is False


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


def test_sampling_recorder_accepts_cloud_extension_key_and_region_stats_preserve_it(tmp_path) -> None:
	storage = JsonStorageAdapter(str(tmp_path / "stats.json"), default_value={"regions": {}}, pretty=True)
	repository = RegionStatsRepository(storage_adapter=storage)
	recorder = SamplingRecorder(stats_repository=repository)
	stats_service = StatisticsQueryService(stats_repository=repository)

	result = RecognitionResult(
		class_id=None,
		plant_key="cloud:野花",
		plant_name="野花",
		display_name="野花",
		confidence=0.91,
		is_recognized=True,
		source="cloud",
		catalog_mapped=False,
		raw_label_name="野花",
		top3=[],
	)

	recorder.record("map_a_r1", result)
	recorder.record("map_a_r1", result)

	snapshot = stats_service.snapshot_for_region("map_a_r1")
	assert len(snapshot.items) == 1
	assert snapshot.items[0].plant_key == "cloud:野花"
	assert snapshot.items[0].display_name == "野花"
	assert snapshot.items[0].count == 2


def test_sampling_pages_render_with_view_models() -> None:
	ctx = StateContext(
		mode="sampling",
		available_maps=[
			{"map_id": "map_a", "display_name": "地图A"},
			{"map_id": "map_b", "display_name": "地图B"},
		],
		selected_map_index=1,
		selected_map_id="map_b",
		available_regions=[
			{"region_id": "map_b_r1", "display_name": "区域1"},
			{"region_id": "map_b_r2", "display_name": "区域2"},
		],
		selected_region_index=0,
		selected_region_id="map_b_r1",
	)

	map_vm = build_view_model(State.MAP_SELECT, ctx)
	region_vm = build_view_model(State.REGION_SELECT, ctx)

	map_lines = MapPage.render(map_vm)
	region_lines = RegionPage.render(region_vm)

	assert map_vm["selected_map_display_name"] == "地图B"
	assert map_vm["selected_map_thumbnail_path"] is None
	assert region_vm["selected_region_display_name"] == "区域1"
	assert region_vm["selected_region_thumbnail_path"] is None
	assert map_lines[0] == "[地图选择]"
	assert region_lines[0] == "[区域选择]"

	# Stats page should render item list in current page.
	from domain.models import MapStatsItem, MapStatsSnapshot, StatsItem, StatsSnapshot

	ctx.current_stats_snapshot = StatsSnapshot(
		region_id="map_b_r1",
		items=[
			StatsItem(
				plant_key="paddy",
				plant_name="paddy",
				display_name="水稻",
				count=3,
				last_confidence=0.88,
				last_seen_at="2026-01-01T00:00:00+00:00",
			)
		],
		page_size=4,
	)

	stats_vm = build_view_model(State.STATS, ctx)
	stats_lines = StatsPage.render(stats_vm)
	assert stats_lines[0] == "[区域统计]"
	assert any("水稻" in line for line in stats_lines)

	ctx.current_map_stats_snapshot = MapStatsSnapshot(
		map_id="map_b",
		map_display_name="地图B",
		total_region_count=2,
		recorded_region_count=1,
		items=[
			MapStatsItem(
				plant_key="banana",
				display_name="香蕉",
				total_count=4,
				covered_region_count=1,
				covered_region_names=["区域1"],
				last_confidence=0.93,
				catalog_mapped=True,
			)
		],
		page_size=4,
	)

	map_stats_vm = build_view_model(State.MAP_STATS, ctx)
	map_stats_lines = MapStatsPage.render(map_stats_vm)
	assert map_stats_lines[0] == "[地图统计]"
	assert any("地图B" in line for line in map_stats_lines)
	assert any("香蕉" in line for line in map_stats_lines)
	assert any("所属区域=区域1" in line for line in map_stats_lines)
	assert map_stats_vm["map_thumbnail_path"] is None
	assert map_stats_vm["items"][0]["covered_regions_text"] == "区域1"


def test_selection_view_models_include_thumbnail_entry_points() -> None:
	ctx = StateContext(
		mode="sampling",
		available_maps=[
			{
				"map_id": "map_a",
				"display_name": "地图A",
				"thumbnail_path": "assets/maps/map_a_thumb.png",
				"regions": [
					{
						"region_id": "map_a_r1",
						"display_name": "区域1",
						"thumbnail_path": "assets/regions/map_a_r1_thumb.png",
					}
				],
			}
		],
		selected_map_index=0,
		selected_map_id="map_a",
		available_regions=[
			{
				"region_id": "map_a_r1",
				"display_name": "区域1",
				"thumbnail_path": "assets/regions/map_a_r1_thumb.png",
			}
		],
		selected_region_index=0,
		selected_region_id="map_a_r1",
	)

	map_vm = build_view_model(State.MAP_SELECT, ctx)
	region_vm = build_view_model(State.REGION_SELECT, ctx)

	assert map_vm["selected_map_thumbnail_path"] == "assets/maps/map_a_thumb.png"
	assert map_vm["map_items"][0]["thumbnail_path"] == "assets/maps/map_a_thumb.png"
	assert region_vm["selected_region_thumbnail_path"] == "assets/regions/map_a_r1_thumb.png"
	assert region_vm["region_items"][0]["thumbnail_path"] == "assets/regions/map_a_r1_thumb.png"


def test_preview_view_model_contains_non_fatal_error_hint() -> None:
	ctx = StateContext(
		mode="normal",
		preview_error_flash_pending=True,
		last_error=ErrorInfo(error_type="InferenceError", message="infer timeout", retryable=False),
	)

	view_model = build_view_model(State.PREVIEW, ctx)

	assert view_model["non_fatal_error_type"] == "InferenceError"
	assert view_model["non_fatal_error_message"] == "infer timeout"


def test_preview_view_model_exposes_last_recognition_source() -> None:
	ctx = StateContext(
		mode="normal",
		last_recognition_result=RecognitionResult(
			class_id=1,
			plant_key="banana",
			plant_name="banana",
			display_name="香蕉",
			confidence=0.94,
			is_recognized=True,
			source="local",
			fallback_used=True,
		),
	)

	view_model = build_view_model(State.PREVIEW, ctx)
	lines = PreviewPage.render(view_model)

	assert view_model["last_recognition_display_name"] == "香蕉"
	assert view_model["last_recognition_source_display_name"] == "本地回退"
	assert any("上次结果: 香蕉" in line for line in lines)
	assert any("识别来源: 本地回退" in line for line in lines)


def test_stats_page_renders_warning_for_data_error() -> None:
	view_model = {
		"mode": "sampling",
		"region_id": "map_a_r1",
		"page": 0,
		"total_pages": 1,
		"items": [],
		"stats_error_type": "DataError",
		"stats_error_message": "corrupted stats json",
	}

	lines = StatsPage.render(view_model)

	assert any("警告: DataError: corrupted stats json" in line for line in lines)


def test_error_page_render_and_renderer_route() -> None:
	ctx = StateContext(
		last_error=ErrorInfo(error_type="CameraError", message="camera unavailable", retryable=True)
	)
	renderer = Renderer()
	emitted: list[list[str]] = []
	renderer._emit = lambda lines: emitted.append(lines)

	view_model = renderer.render(State.ERROR, ctx)

	assert view_model["error_type"] == "CameraError"
	assert emitted
	assert emitted[0][0] == "[错误]"
	assert any("操作: CONFIRM 重试" in line for line in emitted[0])


def test_error_page_render_non_retryable_message() -> None:
	lines = ErrorPage.render(
		{
			"error_type": "ReleaseGateError",
			"error_message": "blocked by policy",
			"retryable": False,
		}
	)

	assert lines[0] == "[错误]"
	assert any("操作: CONFIRM 忽略（不可重试）" in line for line in lines)


def test_additional_state_pages_render_expected_headers() -> None:
	ctx = StateContext(selected_home_option="sampling")

	boot_lines = BootingPage.render(build_view_model(State.BOOTING, ctx))
	home_lines = HomePage.render(build_view_model(State.HOME, ctx))
	preview_lines = PreviewPage.render(build_view_model(State.PREVIEW, ctx))
	infer_lines = InferencingOverlay.render(build_view_model(State.INFERENCING, ctx))

	assert boot_lines[0] == "[启动中]"
	assert home_lines[0] == "[首页]"
	assert any("> 采样统计" in line for line in home_lines)
	assert preview_lines[0] == "[预览]"
	assert infer_lines[0] == "[识别中]"


def test_renderer_routes_for_booting_home_preview_inferencing() -> None:
	from domain.models import MapStatsItem, MapStatsSnapshot

	renderer = Renderer(ui_backend="text")
	emitted: list[list[str]] = []
	renderer._emit = lambda lines: emitted.append(lines)
	ctx = StateContext(selected_home_option="normal")

	renderer.render(State.BOOTING, ctx)
	renderer.render(State.HOME, ctx)
	renderer.render(State.PREVIEW, ctx)
	renderer.render(State.INFERENCING, ctx)
	ctx.current_map_stats_snapshot = MapStatsSnapshot(
		map_id="map_a",
		map_display_name="地图A",
		total_region_count=4,
		recorded_region_count=2,
		items=[
			MapStatsItem(
				plant_key="banana",
				display_name="香蕉",
				total_count=3,
				covered_region_count=2,
				last_confidence=0.91,
				catalog_mapped=True,
			)
		],
		page_size=4,
	)
	renderer.render(State.MAP_STATS, ctx)

	assert emitted[0][0] == "[启动中]"
	assert emitted[1][0] == "[首页]"
	assert emitted[2][0] == "[预览]"
	assert emitted[3][0] == "[识别中]"
	assert emitted[4][0] == "[地图统计]"
