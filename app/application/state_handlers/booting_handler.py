"""BOOTING state handler."""

from __future__ import annotations

from application.events import Event, EventType
from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
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

