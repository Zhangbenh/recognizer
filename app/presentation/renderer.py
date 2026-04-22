"""Renderer that emits compact state snapshots to logger/console."""

from __future__ import annotations

import json
import logging
from typing import Optional

from application.state_context import StateContext
from application.states import State
from presentation.pages import (
	BootingPage,
	DisplayPage,
	ErrorPage,
	HomePage,
	InferencingOverlay,
	MapPage,
	MapStatsPage,
	PreviewPage,
	RegionPage,
	StatsPage,
)
from presentation.view_models import build_view_model


class Renderer:
	"""Render only when state/view changes to reduce terminal noise."""

	def __init__(
		self,
		*,
		logger: Optional[logging.Logger] = None,
		ui_backend: str = "text",
	) -> None:
		self._logger = logger
		self._last_signature: Optional[str] = None
		self._ui_backend = ui_backend
		self._screen_renderer = None

		if ui_backend in {"screen", "both"}:
			self._screen_renderer = self._create_screen_renderer()

	@property
	def needs_live_preview_frames(self) -> bool:
		return self._screen_renderer is not None

	def render(self, state: State, ctx: StateContext) -> dict:
		view_model = build_view_model(state, ctx)
		signature = json.dumps(view_model, sort_keys=True, ensure_ascii=True, default=str)
		should_emit_text = signature != self._last_signature
		self._last_signature = signature

		if should_emit_text and self._ui_backend in {"text", "both"}:
			lines = self._format_lines(state, view_model)
			self._emit(lines)

		if self._screen_renderer is not None:
			self._screen_renderer.render(state, view_model, ctx)

		if state == State.PREVIEW and view_model.get("non_fatal_error_message"):
			ctx.preview_error_flash_pending = False
		return view_model

	def _format_lines(self, state: State, view_model: dict) -> list[str]:
		if state == State.BOOTING:
			return BootingPage.render(view_model)
		if state == State.HOME:
			return HomePage.render(view_model)
		if state == State.MAP_SELECT:
			return MapPage.render(view_model)
		if state == State.MAP_STATS:
			return MapStatsPage.render(view_model)
		if state == State.REGION_SELECT:
			return RegionPage.render(view_model)
		if state == State.PREVIEW:
			return PreviewPage.render(view_model)
		if state == State.CAPTURED:
			return ["[已拍摄]", f"  状态: {view_model.get('status')}", f"  提示: {view_model.get('hint')}"]
		if state == State.INFERENCING:
			return InferencingOverlay.render(view_model)
		if state == State.STATS:
			return StatsPage.render(view_model)
		if state == State.DISPLAY:
			return DisplayPage.render(view_model)
		if state == State.RECORDING:
			return DisplayPage.render_recording(view_model)
		if state == State.ERROR:
			return ErrorPage.render(view_model)

		lines = ["[Render]"]
		for key in sorted(view_model.keys()):
			lines.append(f"  {key}: {view_model[key]}")
		return lines

	def _emit(self, lines: list[str]) -> None:
		text = "\n".join(lines)
		if self._logger:
			self._logger.info("\n%s", text)
		else:
			print(text)

	def close(self) -> None:
		if self._screen_renderer is not None:
			self._screen_renderer.close()
			self._screen_renderer = None

	def _create_screen_renderer(self):
		try:
			from presentation.screen_renderer import PygameScreenRenderer

			return PygameScreenRenderer(logger=self._logger)
		except Exception as exc:
			if self._logger:
				self._logger.warning("screen renderer disabled: %s", exc)
			return None

