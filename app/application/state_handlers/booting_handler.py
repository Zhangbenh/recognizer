"""BOOTING state handler."""

from __future__ import annotations

from application.events import Event, EventType
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.errors import ConfigError
from domain.recognition_service import RecognitionService
from domain.release_gate_service import ReleaseGateService
from infrastructure.config.sampling_config_repository import SamplingConfigRepository


class BootingHandler(BaseStateHandler):
	def __init__(
		self,
		*,
		release_gate_service: ReleaseGateService,
		recognition_service: RecognitionService,
		sampling_config_repository: SamplingConfigRepository,
	) -> None:
		super().__init__(State.BOOTING)
		self._release_gate_service = release_gate_service
		self._recognition_service = recognition_service
		self._sampling_config_repository = sampling_config_repository

	def on_enter(self, ctx: StateContext):
		try:
			self._release_gate_service.ensure_pass()
			self._recognition_service.boot()

			ctx.available_maps = self._sampling_config_repository.list_maps()
			self._validate_sampling_config(ctx.available_maps)
			if ctx.available_maps:
				ctx.selected_map_index = 0
				first_map = ctx.available_maps[0]
				ctx.selected_map_id = str(first_map.get("map_id") or first_map.get("id") or "") or None
			else:
				ctx.selected_map_index = None
				ctx.selected_map_id = None

			return [Event(EventType.BOOT_OK, source="BootingHandler")]
		except Exception as exc:
			ctx.set_error(exc)
			return [
				Event(
					EventType.BOOT_FAIL,
					source="BootingHandler",
					payload={"reason": str(exc)},
				)
			]

	@staticmethod
	def _validate_sampling_config(maps: list[dict]) -> None:
		# Empty map list is allowed; user can stay in MAP_SELECT with no options.
		for index, map_item in enumerate(maps):
			map_id = str(map_item.get("map_id") or map_item.get("id") or "").strip()
			if not map_id:
				raise ConfigError(f"sampling_config map[{index}] missing map_id", retryable=True)

			regions = map_item.get("regions")
			if not isinstance(regions, list) or not regions:
				raise ConfigError(f"sampling_config map '{map_id}' has no regions", retryable=True)

			for region_index, region_item in enumerate(regions):
				region_id = str(region_item.get("region_id") or region_item.get("id") or "").strip()
				if not region_id:
					raise ConfigError(
						f"sampling_config map '{map_id}' region[{region_index}] missing region_id",
						retryable=True,
					)

