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
		self._font_small = pygame.font.SysFont(None, 20)
		self._font_medium = pygame.font.SysFont(None, 24)
		self._font_large = pygame.font.SysFont(None, 30)
		self._ready = True

		self._log_info(
			"screen renderer ready: backend=%s size=%sx%s fullscreen=%s fill=%s",
			os.getenv("SDL_VIDEODRIVER", "<default>"),
			self._width,
			self._height,
			self._fullscreen,
			self._fill_screen,
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
				hint="NAV next | CONFIRM preview | NAV_LONG stats | BACK_LONG map",
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
		self._draw_centered_text("Select Mode", y=56, size="large")

		self._draw_menu_item("normal", selected == "normal", y=132)
		self._draw_menu_item("sampling", selected == "sampling", y=184)
		self._draw_hint(view_model.get("hint"))

	def _draw_menu_item(self, text: str, highlighted: bool, *, y: int) -> None:
		pygame = self._pygame
		screen = self._screen
		font = self._font_medium
		if pygame is None or screen is None or font is None:
			return

		rect = pygame.Rect(70, y - 20, self._width - 140, 40)
		if highlighted:
			pygame.draw.rect(screen, (50, 110, 185), rect, border_radius=8)
			color = (255, 255, 255)
		else:
			pygame.draw.rect(screen, (45, 45, 55), rect, border_radius=8)
			color = (205, 205, 205)

		label = font.render(text.upper(), True, color)
		screen.blit(label, (rect.x + 14, rect.y + 9))

	def _draw_list(self, *, title: str, items: list[str], selected_text: Optional[str], hint: str) -> None:
		pygame = self._pygame
		screen = self._screen
		font = self._font_small
		if pygame is None or screen is None or font is None:
			return

		self._draw_centered_text(title, y=18, size="medium")

		if not items:
			self._draw_centered_text("No items", y=self._height // 2)
			self._draw_hint(hint)
			return

		max_rows = 5
		start_y = 64
		line_h = 40
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
			rect = pygame.Rect(28, start_y + row * line_h, self._width - 56, 34)
			pygame.draw.rect(screen, (65, 95, 145) if selected else (34, 36, 44), rect, border_radius=6)
			marker = ">" if selected else " "
			label = font.render(f"{marker} {text}", True, (245, 245, 245))
			screen.blit(label, (rect.x + 8, rect.y + 8))

		self._draw_hint(hint)

	def _draw_result_panel(self, *, view_model: dict[str, Any], recording: bool) -> None:
		pygame = self._pygame
		screen = self._screen
		font_small = self._font_small
		font_medium = self._font_medium
		if pygame is None or screen is None or font_small is None or font_medium is None:
			return

		panel_w = min(self._width - 32, 420)
		panel_h = 132
		panel_x = (self._width - panel_w) // 2
		panel_y = (self._height - panel_h) // 2

		panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
		panel.fill((0, 0, 0, 190))
		screen.blit(panel, (panel_x, panel_y))

		border_color = (255, 190, 80) if recording else (95, 170, 240)
		pygame.draw.rect(screen, border_color, pygame.Rect(panel_x, panel_y, panel_w, panel_h), 2, border_radius=10)

		name = view_model.get("display_name") or "Unrecognized"
		confidence = view_model.get("confidence")
		if isinstance(confidence, float):
			confidence_text = f"{confidence * 100:.1f}%"
		else:
			confidence_text = "--"

		header = "Recording" if recording else "Result"
		screen.blit(font_small.render(header, True, (200, 220, 255)), (panel_x + 12, panel_y + 10))
		screen.blit(font_medium.render(str(name), True, (255, 255, 255)), (panel_x + 12, panel_y + 44))
		screen.blit(font_small.render(f"confidence: {confidence_text}", True, (220, 220, 220)), (panel_x + 12, panel_y + 78))

		hint = "Recording in progress..." if recording else (view_model.get("hint") or "")
		if hint:
			hint_label = font_small.render(str(hint), True, (236, 236, 236))
			screen.blit(hint_label, (panel_x + 12, panel_y + panel_h - 24))

	def _draw_stats_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		font_small = self._font_small
		font_medium = self._font_medium
		if pygame is None or screen is None or font_small is None or font_medium is None:
			return

		screen.fill((20, 24, 28))
		self._draw_centered_text("Stats", y=16, size="medium")
		region = view_model.get("region_id") or "<none>"
		screen.blit(font_small.render(f"region: {region}", True, (220, 220, 220)), (12, 48))

		page = int(view_model.get("page", 0)) + 1
		total_pages = max(1, int(view_model.get("total_pages", 1)))
		screen.blit(font_small.render(f"page: {page}/{total_pages}", True, (220, 220, 220)), (12, 70))

		error_message = view_model.get("stats_error_message")
		if error_message:
			screen.blit(font_small.render(f"warning: {error_message}", True, (240, 190, 70)), (12, 92))

		items = view_model.get("items") or []
		if not items:
			screen.blit(font_medium.render("No data", True, (180, 180, 180)), (12, 132))
		else:
			base_y = 106
			for index, item in enumerate(items[:4], start=1):
				name = item.get("display_name") or "<unknown>"
				count = item.get("count")
				line = f"{index}. {name}  x{count}"
				screen.blit(font_small.render(line, True, (245, 245, 245)), (12, base_y + (index - 1) * 34))

		self._draw_hint("NAV next page | BACK_LONG region")

	def _draw_error_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		font_small = self._font_small
		font_medium = self._font_medium
		if pygame is None or screen is None or font_small is None or font_medium is None:
			return

		screen.fill((45, 8, 8))
		self._draw_centered_text("Error", y=18, size="large")
		error_type = view_model.get("error_type") or "UnknownError"
		error_message = view_model.get("error_message") or "no details"
		retryable = bool(view_model.get("retryable"))

		screen.blit(font_medium.render(str(error_type), True, (255, 230, 230)), (16, 96))
		screen.blit(font_small.render(str(error_message), True, (255, 210, 210)), (16, 132))
		action = "CONFIRM: retry" if retryable else "CONFIRM: ignore"
		screen.blit(font_small.render(action, True, (255, 255, 255)), (16, self._height - 28))

	def _draw_crosshair(self) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		cx = self._width // 2
		cy = self._height // 2
		size = 18
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
		pad_x = 10
		pad_y = 5
		rect = pygame.Rect(
			12,
			12,
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
		screen.blit(label, (10, self._height - 24))

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
