"""Pygame screen renderer for Raspberry Pi display output."""

from __future__ import annotations

import math
import os
from typing import Any, Optional

from application.state_context import StateContext
from application.states import State


class PygameScreenRenderer:
	"""Render state-driven UI frames to a physical screen with pygame."""

	def __init__(self, *, logger=None) -> None:
		self._logger = logger
		self._pygame = None
		self._screen = None
		self._font_small = None
		self._font_medium = None
		self._font_large = None
		self._ready = False

		# Width/height default to auto detect. Set explicit values when needed.
		self._width = max(0, int(os.getenv("RECOGNIZER_SCREEN_WIDTH", "0")))
		self._height = max(0, int(os.getenv("RECOGNIZER_SCREEN_HEIGHT", "0")))
		self._fullscreen = os.getenv("RECOGNIZER_SCREEN_FULLSCREEN", "1") not in {"0", "false", "False"}
		self._fill_screen = os.getenv("RECOGNIZER_SCREEN_FILL", "1") not in {"0", "false", "False"}
		self._preview_rotation = int(os.getenv("RECOGNIZER_PREVIEW_ROTATION", "0"))
		self._ui_scale = min(2.0, max(1.0, float(os.getenv("RECOGNIZER_UI_SCALE", "1.25"))))
		self._crosshair_color = (40, 240, 120)
		self._bg_color = (12, 16, 22)
		self._panel_bg = (0, 0, 0, 160)

		self._init_pygame()

	@property
	def is_ready(self) -> bool:
		return self._ready

	def _init_pygame(self) -> None:
		try:
			import pygame
		except ImportError as exc:
			raise RuntimeError(
				"pygame is not installed. Install python3-pygame or pip install pygame."
			) from exc

		if "SDL_VIDEODRIVER" not in os.environ:
			# camera_proto verified kmsdrm as the preferred output in current hardware setup.
			os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

		pygame.init()
		display_info = pygame.display.Info()
		if self._width <= 0:
			self._width = int(display_info.current_w or 480)
		if self._height <= 0:
			self._height = int(display_info.current_h or 320)

		flags = pygame.NOFRAME
		if self._fullscreen:
			flags |= pygame.FULLSCREEN

		try:
			screen = pygame.display.set_mode((self._width, self._height), flags)
		except pygame.error as exc:
			if self._fullscreen:
				try:
					screen = pygame.display.set_mode((0, 0), flags)
					self._width, self._height = screen.get_size()
				except pygame.error:
					pygame.quit()
					raise RuntimeError(
						f"failed to initialize pygame display backend ({os.getenv('SDL_VIDEODRIVER')}): {exc}"
					) from exc
			else:
				pygame.quit()
				raise RuntimeError(
					f"failed to initialize pygame display backend ({os.getenv('SDL_VIDEODRIVER')}): {exc}"
				) from exc

		pygame.display.set_caption("Plant Recognizer")
		self._pygame = pygame
		self._screen = screen
		self._font_small = pygame.font.Font(None, self._scaled_px(22))
		self._font_medium = pygame.font.Font(None, self._scaled_px(30))
		self._font_large = pygame.font.Font(None, self._scaled_px(40))
		self._ready = True

		self._log_info(
			"screen renderer ready: backend=%s size=%sx%s fullscreen=%s fill=%s ui_scale=%.2f",
			os.getenv("SDL_VIDEODRIVER", "<default>"),
			self._width,
			self._height,
			self._fullscreen,
			self._fill_screen,
			self._ui_scale,
		)

	def render(self, state: State, view_model: dict[str, Any], ctx: StateContext) -> None:
		if not self._ready:
			return

		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		self._drain_events()

		frame_surface = self._frame_surface_for_state(state, ctx)
		screen.fill(self._bg_color)
		if frame_surface is not None:
			offset_x = (self._width - frame_surface.get_width()) // 2
			offset_y = (self._height - frame_surface.get_height()) // 2
			screen.blit(frame_surface, (offset_x, offset_y))

		if state == State.BOOTING:
			self._draw_centered_text("Plant Recognizer", y=self._height // 2 - 24, size="large")
			self._draw_centered_text("Booting...", y=self._height // 2 + 8)
		elif state == State.HOME:
			self._draw_menu(view_model=view_model)
		elif state == State.MAP_SELECT:
			self._draw_list(
				title="Map Select",
				items=view_model.get("available_map_names") or [],
				selected_text=view_model.get("selected_map_display_name"),
				hint="NAV next | CONFIRM select | BACK_LONG home",
			)
		elif state == State.REGION_SELECT:
			self._draw_list(
				title="Region Select",
				items=view_model.get("available_region_names") or [],
				selected_text=view_model.get("selected_region_display_name"),
				hint="BTN2_SHORT next | BTN1_SHORT preview | BTN1_LONG stats | BTN2_LONG map",
			)
		elif state == State.PREVIEW:
			self._draw_crosshair()
			self._draw_hint(view_model.get("hint"))
			non_fatal = view_model.get("non_fatal_error_message")
			if non_fatal:
				self._draw_badge(f"WARN: {non_fatal}", color=(240, 190, 70))
		elif state == State.CAPTURED:
			self._draw_badge("Captured", color=(88, 200, 255))
		elif state == State.INFERENCING:
			self._draw_overlay_message("AI inferencing...")
		elif state == State.DISPLAY:
			self._draw_result_panel(view_model=view_model, recording=False)
		elif state == State.RECORDING:
			self._draw_result_panel(view_model=view_model, recording=True)
		elif state == State.STATS:
			self._draw_stats_panel(view_model=view_model)
		elif state == State.ERROR:
			self._draw_error_panel(view_model=view_model)

		pygame.display.flip()

	def close(self) -> None:
		if not self._ready:
			return

		pygame = self._pygame
		self._ready = False
		self._screen = None
		self._font_small = None
		self._font_medium = None
		self._font_large = None
		self._pygame = None

		if pygame is not None:
			pygame.quit()

	def _frame_surface_for_state(self, state: State, ctx: StateContext):
		if state not in {
			State.PREVIEW,
			State.CAPTURED,
			State.INFERENCING,
			State.DISPLAY,
			State.RECORDING,
		}:
			return None

		frame = ctx.preview_frame if ctx.preview_frame is not None else ctx.last_captured_frame
		if frame is None:
			return None

		return self._to_screen_surface(frame)

	def _to_screen_surface(self, frame: Any):
		pygame = self._pygame
		if pygame is None:
			return None

		try:
			import numpy as np
		except ImportError:
			return None

		array = frame
		if isinstance(array, np.ndarray) and array.ndim == 4 and array.shape[0] == 1:
			array = array[0]

		if not isinstance(array, np.ndarray):
			return None
		if array.ndim != 3 or array.shape[2] != 3:
			return None

		array = array.astype("uint8", copy=False)
		surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
		if self._preview_rotation in {90, 180, 270}:
			surface = pygame.transform.rotate(surface, self._preview_rotation)
		return self._fit_surface_to_screen(surface)

	def _fit_surface_to_screen(self, surface):
		pygame = self._pygame
		if pygame is None:
			return surface

		surface_width, surface_height = surface.get_size()
		if surface_width <= 0 or surface_height <= 0:
			return surface

		if self._fill_screen:
			scale = max(self._width / surface_width, self._height / surface_height)
		else:
			scale = min(self._width / surface_width, self._height / surface_height)

		target_size = (
			max(1, int(math.ceil(surface_width * scale))),
			max(1, int(math.ceil(surface_height * scale))),
		)
		return pygame.transform.smoothscale(surface, target_size)

	def _draw_menu(self, *, view_model: dict[str, Any]) -> None:
		selected = str(view_model.get("selected_home_option") or "normal")
		self._draw_centered_text("Select Mode", y=self._scaled_px(34), size="large")

		self._draw_menu_item("normal", selected == "normal", y=int(self._height * 0.42))
		self._draw_menu_item("sampling", selected == "sampling", y=int(self._height * 0.62))
		self._draw_hint(view_model.get("hint"))

	def _draw_menu_item(self, text: str, highlighted: bool, *, y: int) -> None:
		pygame = self._pygame
		screen = self._screen
		font = self._font_medium
		if pygame is None or screen is None or font is None:
			return

		item_h = max(self._scaled_px(44), font.get_height() + self._scaled_px(16))
		rect = pygame.Rect(
			self._scaled_px(34),
			y - (item_h // 2),
			self._width - self._scaled_px(68),
			item_h,
		)
		if highlighted:
			pygame.draw.rect(screen, (50, 110, 185), rect, border_radius=8)
			color = (255, 255, 255)
		else:
			pygame.draw.rect(screen, (45, 45, 55), rect, border_radius=8)
			color = (205, 205, 205)

		label = font.render(text.upper(), True, color)
		screen.blit(label, (rect.x + self._scaled_px(14), rect.y + (item_h - label.get_height()) // 2))

	def _draw_list(self, *, title: str, items: list[str], selected_text: Optional[str], hint: str) -> None:
		pygame = self._pygame
		screen = self._screen
		item_font = self._font_medium
		hint_font = self._font_small
		if pygame is None or screen is None or item_font is None or hint_font is None:
			return

		self._draw_centered_text(title, y=self._scaled_px(14), size="medium")

		if not items:
			self._draw_centered_text("No items", y=self._height // 2)
			self._draw_hint(hint)
			return

		max_rows = 3
		start_y = self._scaled_px(56)
		line_h = max(self._scaled_px(58), item_font.get_height() + self._scaled_px(18))
		selected_index = 0
		for index, text in enumerate(items):
			if text == selected_text:
				selected_index = index
				break

		window_start = max(0, min(selected_index - (max_rows // 2), max(0, len(items) - max_rows)))
		window = items[window_start : window_start + max_rows]

		for row, text in enumerate(window):
			item_index = window_start + row
			selected = item_index == selected_index
			rect = pygame.Rect(
				self._scaled_px(20),
				start_y + row * line_h,
				self._width - self._scaled_px(40),
				line_h - self._scaled_px(6),
			)
			pygame.draw.rect(screen, (65, 95, 145) if selected else (34, 36, 44), rect, border_radius=6)
			marker = ">" if selected else " "
			label = item_font.render(f"{marker} {text}", True, (245, 245, 245))
			screen.blit(label, (rect.x + self._scaled_px(8), rect.y + (rect.height - label.get_height()) // 2))

		hint_label = hint_font.render(str(hint), True, (236, 236, 236))
		screen.blit(
			hint_label,
			(self._scaled_px(8), self._height - hint_label.get_height() - self._scaled_px(6)),
		)

	def _draw_result_panel(self, *, view_model: dict[str, Any], recording: bool) -> None:
		pygame = self._pygame
		screen = self._screen
		header_font = self._font_medium
		name_font = self._font_large
		meta_font = self._font_medium
		if pygame is None or screen is None or header_font is None or name_font is None or meta_font is None:
			return

		panel_w = min(self._width - self._scaled_px(24), int(self._width * 0.92))
		panel_h = max(
			self._scaled_px(180),
			header_font.get_height() + name_font.get_height() + meta_font.get_height() * 2 + self._scaled_px(42),
		)
		panel_x = (self._width - panel_w) // 2
		panel_y = (self._height - panel_h) // 2

		panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
		panel.fill((0, 0, 0, 190))
		screen.blit(panel, (panel_x, panel_y))

		border_color = (255, 190, 80) if recording else (95, 170, 240)
		pygame.draw.rect(
			screen,
			border_color,
			pygame.Rect(panel_x, panel_y, panel_w, panel_h),
			2,
			border_radius=self._scaled_px(10),
		)

		name = view_model.get("display_name") or "Unrecognized"
		confidence = view_model.get("confidence")
		if isinstance(confidence, float):
			confidence_text = f"{confidence * 100:.1f}%"
		else:
			confidence_text = "--"

		header = "Recording" if recording else "Result"
		line_top = panel_y + self._scaled_px(12)
		line_gap = self._scaled_px(10)
		line2 = line_top + header_font.get_height() + line_gap
		line3 = line2 + name_font.get_height() + line_gap
		screen.blit(header_font.render(header, True, (200, 220, 255)), (panel_x + self._scaled_px(12), line_top))
		screen.blit(name_font.render(str(name), True, (255, 255, 255)), (panel_x + self._scaled_px(12), line2))
		screen.blit(
			meta_font.render(f"confidence: {confidence_text}", True, (220, 220, 220)),
			(panel_x + self._scaled_px(12), line3),
		)

		hint = "Recording in progress..." if recording else (view_model.get("hint") or "")
		if hint:
			hint_label = meta_font.render(str(hint), True, (236, 236, 236))
			screen.blit(
				hint_label,
				(panel_x + self._scaled_px(12), panel_y + panel_h - hint_label.get_height() - self._scaled_px(8)),
			)

	def _draw_stats_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		meta_font = self._font_medium
		item_font = self._font_medium
		if pygame is None or screen is None or meta_font is None or item_font is None:
			return

		screen.fill((20, 24, 28))
		self._draw_centered_text("Stats", y=self._scaled_px(12), size="medium")
		region = view_model.get("region_id") or "<none>"
		region_y = self._scaled_px(44)
		screen.blit(meta_font.render(f"region: {region}", True, (220, 220, 220)), (self._scaled_px(12), region_y))

		page = int(view_model.get("page", 0)) + 1
		total_pages = max(1, int(view_model.get("total_pages", 1)))
		page_y = region_y + meta_font.get_height() + self._scaled_px(4)
		screen.blit(meta_font.render(f"page: {page}/{total_pages}", True, (220, 220, 220)), (self._scaled_px(12), page_y))

		error_message = view_model.get("stats_error_message")
		warning_y = page_y + meta_font.get_height() + self._scaled_px(4)
		if error_message:
			screen.blit(
				meta_font.render(f"warning: {error_message}", True, (240, 190, 70)),
				(self._scaled_px(12), warning_y),
			)

		items = view_model.get("items") or []
		items_start_y = warning_y + meta_font.get_height() + self._scaled_px(6) if error_message else warning_y
		row_h = item_font.get_height() + self._scaled_px(8)
		max_items = max(1, (self._height - items_start_y - self._scaled_px(30)) // row_h)
		if not items:
			screen.blit(item_font.render("No data", True, (180, 180, 180)), (self._scaled_px(12), items_start_y))
		else:
			for index, item in enumerate(items[:max_items], start=1):
				name = item.get("display_name") or "<unknown>"
				count = item.get("count")
				line = f"{index}. {name}  x{count}"
				screen.blit(
					item_font.render(line, True, (245, 245, 245)),
					(self._scaled_px(12), items_start_y + (index - 1) * row_h),
				)

		hint_label = meta_font.render("NAV next page | BACK_LONG region", True, (236, 236, 236))
		screen.blit(
			hint_label,
			(self._scaled_px(8), self._height - hint_label.get_height() - self._scaled_px(6)),
		)

	def _draw_error_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		head_font = self._font_large
		body_font = self._font_medium
		if pygame is None or screen is None or head_font is None or body_font is None:
			return

		screen.fill((45, 8, 8))
		self._draw_centered_text("Error", y=self._scaled_px(14), size="large")
		error_type = view_model.get("error_type") or "UnknownError"
		error_message = view_model.get("error_message") or "no details"
		retryable = bool(view_model.get("retryable"))

		error_y = int(self._height * 0.34)
		screen.blit(head_font.render(str(error_type), True, (255, 230, 230)), (self._scaled_px(16), error_y))
		screen.blit(
			body_font.render(str(error_message), True, (255, 210, 210)),
			(self._scaled_px(16), error_y + head_font.get_height() + self._scaled_px(10)),
		)
		action = "CONFIRM: retry" if retryable else "CONFIRM: ignore"
		action_label = body_font.render(action, True, (255, 255, 255))
		screen.blit(
			action_label,
			(self._scaled_px(16), self._height - action_label.get_height() - self._scaled_px(10)),
		)

	def _draw_crosshair(self) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		cx = self._width // 2
		cy = self._height // 2
		size = self._scaled_px(16)
		pygame.draw.line(screen, self._crosshair_color, (cx - size, cy), (cx + size, cy), 2)
		pygame.draw.line(screen, self._crosshair_color, (cx, cy - size), (cx, cy + size), 2)

	def _draw_overlay_message(self, text: str) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		overlay = pygame.Surface((self._width, self._height), pygame.SRCALPHA)
		overlay.fill((0, 0, 0, 120))
		screen.blit(overlay, (0, 0))
		self._draw_centered_text(text, y=self._height // 2 - 6)

	def _draw_badge(self, text: str, *, color: tuple[int, int, int]) -> None:
		pygame = self._pygame
		screen = self._screen
		font = self._font_small
		if pygame is None or screen is None or font is None:
			return

		label = font.render(text, True, (255, 255, 255))
		pad_x = self._scaled_px(10)
		pad_y = self._scaled_px(5)
		rect = pygame.Rect(
			self._scaled_px(12),
			self._scaled_px(12),
			label.get_width() + pad_x * 2,
			label.get_height() + pad_y * 2,
		)
		pygame.draw.rect(screen, color, rect, border_radius=8)
		screen.blit(label, (rect.x + pad_x, rect.y + pad_y))

	def _draw_hint(self, hint: Any) -> None:
		if not hint:
			return

		pygame = self._pygame
		screen = self._screen
		font = self._font_small
		if pygame is None or screen is None or font is None:
			return

		label = font.render(str(hint), True, (236, 236, 236))
		screen.blit(label, (self._scaled_px(8), self._height - label.get_height() - self._scaled_px(6)))

	def _draw_centered_text(self, text: str, *, y: int, size: str = "medium") -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		if size == "large":
			font = self._font_large
		elif size == "small":
			font = self._font_small
		else:
			font = self._font_medium

		if font is None:
			return

		label = font.render(text, True, (255, 255, 255))
		screen.blit(label, ((self._width - label.get_width()) // 2, y))

	def _drain_events(self) -> None:
		pygame = self._pygame
		if pygame is None:
			return

		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				self._log_info("screen quit event received")

	def _log_info(self, msg: str, *args: Any) -> None:
		if self._logger:
			self._logger.info(msg, *args)

	def _scaled_px(self, value: int) -> int:
		return max(12, int(round(value * self._ui_scale)))
