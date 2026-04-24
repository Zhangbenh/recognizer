"""Pygame screen renderer for Raspberry Pi display output."""

from __future__ import annotations

import math
import os
from pathlib import Path
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
		self._repo_root = Path(__file__).resolve().parents[2]
		self._image_cache: dict[tuple[str, str, int, int, bool], Any] = {}
		self._font_path: str | None = None
		self._font_label = "default"
		self._ui_scale_override = os.getenv("RECOGNIZER_UI_SCALE", "").strip()

		self._width = max(0, int(os.getenv("RECOGNIZER_SCREEN_WIDTH", "0")))
		self._height = max(0, int(os.getenv("RECOGNIZER_SCREEN_HEIGHT", "0")))
		self._fullscreen = os.getenv("RECOGNIZER_SCREEN_FULLSCREEN", "1") not in {"0", "false", "False"}
		self._fill_screen = os.getenv("RECOGNIZER_SCREEN_FILL", "1") not in {"0", "false", "False"}
		self._preview_rotation = int(os.getenv("RECOGNIZER_PREVIEW_ROTATION", "0"))
		self._ui_scale = 1.0
		self._crosshair_color = (40, 240, 120)
		self._bg_color = (12, 16, 22)
		self._panel_bg = (0, 0, 0, 160)
		self._startup_screen_path = self._resolve_startup_screen_path()

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
			os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

		pygame.init()
		display_info = pygame.display.Info()
		if self._width <= 0:
			self._width = int(display_info.current_w or 480)
		if self._height <= 0:
			self._height = int(display_info.current_h or 320)
		self._ui_scale = self._resolve_ui_scale()

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
		self._font_path = self._resolve_font_path(pygame)
		self._font_small = self._load_font(self._scaled_px(22))
		self._font_medium = self._load_font(self._scaled_px(30))
		self._font_large = self._load_font(self._scaled_px(40))
		self._ready = True

		self._log_info(
			"screen renderer ready: backend=%s size=%sx%s fullscreen=%s fill=%s ui_scale=%.2f font=%s",
			os.getenv("SDL_VIDEODRIVER", "<default>"),
			self._width,
			self._height,
			self._fullscreen,
			self._fill_screen,
			self._ui_scale,
			self._font_label,
		)

	def _resolve_font_path(self, pygame) -> str | None:
		explicit_path = os.getenv("RECOGNIZER_FONT_PATH", "").strip()
		if explicit_path:
			candidate = Path(explicit_path)
			if candidate.exists():
				self._font_label = str(candidate)
				return str(candidate)

		fonts_dir = self._repo_root / "assets" / "fonts"
		for pattern in ("*.ttf", "*.otf", "*.ttc"):
			for candidate in sorted(fonts_dir.glob(pattern)):
				self._font_label = str(candidate.name)
				return str(candidate)

		family_candidates = [
			name.strip()
			for name in os.getenv("RECOGNIZER_FONT_FAMILY", "").split(";")
			if name.strip()
		]
		family_candidates.extend(
			[
				"Microsoft YaHei",
				"SimHei",
				"Noto Sans CJK SC",
				"Noto Sans SC",
				"Source Han Sans SC",
				"WenQuanYi Zen Hei",
				"PingFang SC",
				"Arial Unicode MS",
			]
		)

		for family in family_candidates:
			match = pygame.font.match_font(family)
			if match:
				self._font_label = family
				return match

		self._font_label = "pygame-default"
		return None

	def _load_font(self, size: int):
		pygame = self._pygame
		if pygame is None:
			return None

		if self._font_path:
			try:
				return pygame.font.Font(self._font_path, size)
			except Exception:
				self._log_info("failed to load font %s, fallback to default", self._font_path)

		return pygame.font.Font(None, size)

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
			self._draw_startup_screen()
		elif state == State.HOME:
			self._draw_menu(view_model=view_model)
		elif state == State.MAP_SELECT:
			self._draw_selection_gallery(
				title="地图选择",
				items=view_model.get("map_items") or [],
				selected_id=view_model.get("selected_map_id"),
				hint=str(view_model.get("hint") or ""),
				hero_title=view_model.get("selected_map_display_name") or "未选择地图",
				hero_subtitle="",
			)
		elif state == State.REGION_SELECT:
			self._draw_selection_gallery(
				title="区域选择",
				items=view_model.get("region_items") or [],
				selected_id=view_model.get("selected_region_id"),
				hint=str(view_model.get("hint") or ""),
				hero_title=view_model.get("selected_region_display_name") or "未选择区域",
				hero_subtitle=str(view_model.get("selected_map_display_name") or view_model.get("selected_map_id") or ""),
			)
		elif state == State.MAP_STATS:
			self._draw_map_stats_panel(view_model=view_model)
		elif state == State.PREVIEW:
			self._draw_crosshair()
			self._draw_preview_result_source(view_model=view_model)
			self._draw_hint(view_model.get("hint"))
			non_fatal = view_model.get("non_fatal_error_message")
			if non_fatal:
				self._draw_badge(f"警告: {non_fatal}", color=(240, 190, 70))
		elif state == State.CAPTURED:
			self._draw_badge("已拍摄", color=(88, 200, 255))
		elif state == State.INFERENCING:
			self._draw_overlay_message("AI 正在识别...")
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
		self._image_cache.clear()

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
		return self._pygame.transform.smoothscale(surface, target_size)

	def _fit_surface_to_box(self, surface, *, width: int, height: int, cover: bool):
		pygame = self._pygame
		if pygame is None:
			return surface

		surface_width, surface_height = surface.get_size()
		if surface_width <= 0 or surface_height <= 0:
			return surface

		if cover:
			scale = max(width / surface_width, height / surface_height)
		else:
			scale = min(width / surface_width, height / surface_height)

		target_size = (
			max(1, int(math.ceil(surface_width * scale))),
			max(1, int(math.ceil(surface_height * scale))),
		)
		return pygame.transform.smoothscale(surface, target_size)

	def _resolve_startup_screen_path(self) -> Path:
		assets_path = self._repo_root / "assets" / "startup" / "startup_screen.png"
		if assets_path.exists():
			return assets_path
		root_path = self._repo_root / "startup_screen.png"
		if root_path.exists():
			return root_path
		return assets_path

	def _draw_startup_screen(self) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		surface = self._get_media_surface(
			self._startup_screen_path,
			label="startup-screen",
			width=max(1, self._width),
			height=max(1, self._height),
			cover=True,
		)
		if surface is not None:
			screen.blit(surface, (0, 0))
			return

		self._draw_centered_text("植物识别系统", y=self._height // 2 - self._scaled_px(28), size="large")
		self._draw_centered_text("启动中...", y=self._height // 2 + self._scaled_px(8))

	def _draw_menu(self, *, view_model: dict[str, Any]) -> None:
		selected = str(view_model.get("selected_home_option") or "normal")
		self._draw_centered_text("选择模式", y=self._scaled_px(28), size="large")
		self._draw_menu_item("普通识别", selected == "normal", y=int(self._height * 0.42))
		self._draw_menu_item("采样统计", selected == "sampling", y=int(self._height * 0.62))
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

		label = font.render(text, True, color)
		screen.blit(label, (rect.x + self._scaled_px(14), rect.y + (item_h - label.get_height()) // 2))

	def _draw_selection_gallery(
		self,
		*,
		title: str,
		items: list[dict[str, Any]],
		selected_id: Any,
		hint: str,
		hero_title: str,
		hero_subtitle: str,
	) -> None:
		pygame = self._pygame
		screen = self._screen
		caption_font = self._font_small
		if pygame is None or screen is None or caption_font is None:
			return

		portrait = self._is_portrait_layout()
		self._draw_centered_text(title, y=self._scaled_px(10), size="small" if portrait else "medium")

		if not items:
			self._draw_centered_text("暂无可用图片", y=self._height // 2)
			self._draw_hint(hint)
			return

		selected_index = 0
		for index, item in enumerate(items):
			if str(item.get("id") or "") == str(selected_id or ""):
				selected_index = index
				break

		selected_item = items[selected_index]
		margin = self._scaled_px(10)
		gap = self._scaled_px(8)
		hint_h = self._hint_block_height(hint, max_lines=2)
		thumb_label_h = self._thumbnail_label_height()
		columns = 4 if portrait else 5
		rows = 2 if portrait else 1
		page_size = columns * rows
		thumb_width = max(
			self._scaled_px(70),
			(self._width - margin * 2 - gap * max(0, columns - 1)) // max(1, columns),
		)
		thumb_media_h = max(
			self._scaled_px(54),
			min(self._scaled_px(96 if portrait else 84), int(self._height * (0.12 if portrait else 0.12))),
		)
		thumb_h = thumb_media_h + thumb_label_h
		caption_title_font = self._font_small if portrait else self._font_medium
		caption_pad = self._scaled_px(8)
		caption_height = caption_pad * 2 + (caption_title_font.get_height() if caption_title_font else 0)
		if hero_subtitle:
			caption_height += caption_font.get_height() + self._scaled_px(2)
		grid_total_h = rows * thumb_h + max(0, rows - 1) * gap
		hero_top = self._scaled_px(44)
		grid_top = self._height - hint_h - grid_total_h - self._scaled_px(14)
		hero_height = max(self._scaled_px(150), grid_top - hero_top - self._scaled_px(10))
		hero_rect = pygame.Rect(
			margin,
			hero_top,
			self._width - margin * 2,
			hero_height,
		)
		self._draw_media_card(
			rect=hero_rect,
			thumbnail_path=selected_item.get("thumbnail_path"),
			label=str(hero_title or selected_item.get("display_name") or ""),
			highlighted=True,
			cover=True,
			show_label=False,
		)

		caption_rect = pygame.Rect(
			hero_rect.x,
			hero_rect.bottom - caption_height,
			hero_rect.width,
			caption_height,
		)
		caption = pygame.Surface((caption_rect.width, caption_rect.height), pygame.SRCALPHA)
		caption.fill((0, 0, 0, 165))
		screen.blit(caption, caption_rect.topleft)
		self._blit_text(
			str(hero_title),
			font=caption_title_font,
			x=caption_rect.x + self._scaled_px(10),
			y=caption_rect.y + caption_pad - self._scaled_px(1),
			max_width=caption_rect.width - self._scaled_px(20),
			max_lines=1,
		)
		if hero_subtitle:
			subtitle_y = caption_rect.y + caption_pad + caption_title_font.get_height()
			self._blit_text(
				str(hero_subtitle),
				font=caption_font,
				x=caption_rect.x + self._scaled_px(10),
				y=subtitle_y,
				color=(214, 224, 240),
				max_width=caption_rect.width - self._scaled_px(20),
				max_lines=1,
			)

		thumb_y = hero_rect.bottom + self._scaled_px(10)
		window_start = (selected_index // page_size) * page_size
		visible_items = items[window_start : window_start + page_size]

		for slot_index in range(page_size):
			row_index = slot_index // columns
			column_index = slot_index % columns
			thumb_rect = pygame.Rect(
				margin + column_index * (thumb_width + gap),
				thumb_y + row_index * (thumb_h + gap),
				thumb_width,
				thumb_h,
			)
			if slot_index < len(visible_items):
				item = visible_items[slot_index]
				actual_index = window_start + slot_index
				self._draw_media_card(
					rect=thumb_rect,
					thumbnail_path=item.get("thumbnail_path"),
					label=str(item.get("display_name") or item.get("id") or ""),
					highlighted=actual_index == selected_index,
					cover=False,
					show_label=True,
				)
			else:
				self._draw_empty_media_slot(rect=thumb_rect)

		page_badge = f"{selected_index + 1}/{len(items)}"
		badge = caption_font.render(page_badge, True, (255, 255, 255))
		badge_rect = pygame.Rect(
			hero_rect.right - badge.get_width() - self._scaled_px(24),
			hero_rect.y + self._scaled_px(10),
			badge.get_width() + self._scaled_px(12),
			badge.get_height() + self._scaled_px(8),
		)
		pygame.draw.rect(screen, (32, 44, 68), badge_rect, border_radius=self._scaled_px(8))
		screen.blit(badge, (badge_rect.x + self._scaled_px(6), badge_rect.y + self._scaled_px(4)))

		self._draw_hint(hint)

	def _draw_empty_media_slot(self, *, rect) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		placeholder = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
		placeholder.fill((18, 22, 30, 180))
		screen.blit(placeholder, rect.topleft)
		pygame.draw.rect(screen, (58, 70, 92), rect, 1, border_radius=self._scaled_px(8))

	def _draw_media_card(
		self,
		*,
		rect,
		thumbnail_path: Any,
		label: str,
		highlighted: bool,
		cover: bool,
		show_label: bool,
	) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None:
			return

		surface = self._get_media_surface(
			thumbnail_path,
			label=label,
			width=max(1, rect.width),
			height=max(1, rect.height),
			cover=cover,
		)
		if surface is not None:
			screen.blit(surface, rect.topleft)

		border_color = (255, 214, 92) if highlighted else (72, 86, 108)
		pygame.draw.rect(screen, border_color, rect, 3 if highlighted else 1, border_radius=self._scaled_px(8))

		if show_label:
			label_font = self._font_small
			label_pad_y = self._scaled_px(4)
			label_h = max(
				self._scaled_px(26),
				(label_font.get_height() if label_font is not None else self._scaled_px(16)) + label_pad_y * 2,
			)
			overlay = pygame.Surface((rect.width, label_h), pygame.SRCALPHA)
			overlay.fill((0, 0, 0, 165))
			screen.blit(overlay, (rect.x, rect.bottom - label_h))
			self._blit_text(
				label,
				font=label_font,
				x=rect.x + self._scaled_px(6),
				y=rect.bottom - label_h + label_pad_y,
				max_width=rect.width - self._scaled_px(12),
				max_lines=1,
			)

	def _get_media_surface(self, thumbnail_path: Any, *, label: str, width: int, height: int, cover: bool):
		pygame = self._pygame
		if pygame is None:
			return None

		cache_key = (str(thumbnail_path or ""), str(label), width, height, cover)
		cached = self._image_cache.get(cache_key)
		if cached is not None:
			return cached

		surface = pygame.Surface((width, height))
		asset_path = self._resolve_asset_path(thumbnail_path)
		loaded = self._load_media_surface(asset_path)
		if loaded is not None:
			fitted = self._fit_surface_to_box(loaded, width=width, height=height, cover=cover)
			surface.fill((16, 20, 26))
			surface.blit(fitted, fitted.get_rect(center=(width // 2, height // 2)))
		else:
			surface = self._build_placeholder_surface(width=width, height=height, label=label)

		self._image_cache[cache_key] = surface
		return surface

	def _load_media_surface(self, asset_path: Path | None):
		pygame = self._pygame
		if pygame is None or asset_path is None:
			return None

		for candidate in self._candidate_media_paths(asset_path):
			if not candidate.exists():
				continue
			try:
				loaded = pygame.image.load(str(candidate))
				return loaded.convert_alpha() if loaded.get_alpha() is not None else loaded.convert()
			except Exception as exc:
				fallback = self._load_media_surface_via_pillow(candidate)
				if fallback is not None:
					return fallback
				self._log_info("screen asset load failed: path=%s reason=%s", candidate, exc)
		return None

	def _candidate_media_paths(self, asset_path: Path) -> list[Path]:
		candidates = [asset_path]
		if asset_path.suffix.lower() == ".png":
			bmp_candidate = asset_path.with_suffix(".bmp")
			if bmp_candidate != asset_path:
				candidates.append(bmp_candidate)
		return candidates

	def _load_media_surface_via_pillow(self, asset_path: Path):
		pygame = self._pygame
		if pygame is None:
			return None
		try:
			from PIL import Image
		except ImportError:
			return None

		try:
			with Image.open(asset_path) as image:
				rgba = image.convert("RGBA")
				return pygame.image.fromstring(rgba.tobytes(), rgba.size, "RGBA")
		except Exception:
			return None

	def _build_placeholder_surface(self, *, width: int, height: int, label: str):
		pygame = self._pygame
		if pygame is None:
			return None

		palette = [
			((44, 92, 152), (15, 30, 54)),
			((102, 86, 178), (28, 20, 58)),
			((44, 132, 108), (15, 43, 40)),
			((146, 92, 52), (48, 30, 18)),
			((124, 56, 96), (38, 15, 32)),
		]
		palette_index = sum(ord(ch) for ch in str(label)) % len(palette)
		primary, secondary = palette[palette_index]

		surface = pygame.Surface((width, height))
		surface.fill(primary)
		inner = pygame.Rect(
			self._scaled_px(6),
			self._scaled_px(6),
			max(1, width - self._scaled_px(12)),
			max(1, height - self._scaled_px(12)),
		)
		pygame.draw.rect(surface, secondary, inner, border_radius=self._scaled_px(10))
		pygame.draw.rect(surface, (255, 255, 255), inner, 1, border_radius=self._scaled_px(10))
		pygame.draw.line(surface, (255, 255, 255), (inner.left, inner.bottom), (inner.right, inner.top), 2)
		pygame.draw.circle(surface, (255, 244, 196), (inner.right - self._scaled_px(18), inner.top + self._scaled_px(16)), self._scaled_px(8))

		font = self._font_medium if height >= self._scaled_px(110) else self._font_small
		if font is None:
			return surface

		lines = self._wrap_text(
			font=font,
			text=str(label or "未配置图片"),
			max_width=max(20, width - self._scaled_px(20)),
			max_lines=3,
		)
		line_h = font.get_height() + self._scaled_px(2)
		text_top = (height - line_h * len(lines)) // 2
		for index, line in enumerate(lines):
			text_surface = font.render(line, True, (255, 255, 255))
			surface.blit(text_surface, ((width - text_surface.get_width()) // 2, text_top + index * line_h))

		return surface

	def _resolve_asset_path(self, thumbnail_path: Any) -> Path | None:
		if not thumbnail_path:
			return None
		path = Path(str(thumbnail_path))
		if path.is_absolute():
			return path
		return self._repo_root / path

	def _wrap_text(self, *, font, text: str, max_width: int, max_lines: int) -> list[str]:
		if font is None:
			return [text]
		text = str(text or "")
		if not text:
			return [""]

		lines: list[str] = []
		current = ""
		consumed = 0
		for char in text:
			candidate = current + char
			if current and font.size(candidate)[0] > max_width:
				lines.append(current)
				current = char
				if len(lines) >= max_lines - 1:
					consumed += 1
					break
			else:
				current = candidate
			consumed += 1

		if len(lines) < max_lines and current:
			lines.append(current)

		if consumed < len(text) and lines:
			last = lines[-1]
			if len(last) >= 2:
				lines[-1] = last[:-1] + "…"
			else:
				lines[-1] = last + "…"

		return lines[:max_lines]

	def _draw_result_panel(self, *, view_model: dict[str, Any], recording: bool) -> None:
		pygame = self._pygame
		screen = self._screen
		header_font = self._font_medium
		name_font = self._font_large
		meta_font = self._font_medium
		if pygame is None or screen is None or header_font is None or name_font is None or meta_font is None:
			return

		panel_w = min(self._width - self._scaled_px(24), int(self._width * 0.92))
		padding_x = self._scaled_px(12)
		padding_top = self._scaled_px(12)
		padding_bottom = self._scaled_px(12)
		line_gap = self._scaled_px(10)
		meta_gap = self._scaled_px(4)
		hint_gap = self._scaled_px(10)
		content_w = max(self._scaled_px(80), panel_w - padding_x * 2)
		panel_x = (self._width - panel_w) // 2

		name = view_model.get("display_name") or "未识别"
		confidence = view_model.get("confidence")
		if isinstance(confidence, float):
			confidence_text = f"{confidence * 100:.1f}%"
		else:
			confidence_text = "--"
		source_text = str(view_model.get("source_display_name") or "未知")

		header = "记录中" if recording else "识别结果"
		hint = "正在写入统计..." if recording else (view_model.get("hint") or "")
		hint_lines = self._wrap_text(font=meta_font, text=str(hint), max_width=content_w, max_lines=2) if hint else []

		panel_h = padding_top + header_font.get_height() + line_gap
		panel_h += name_font.get_height() + line_gap
		panel_h += meta_font.get_height() + meta_gap
		panel_h += meta_font.get_height()
		if hint_lines:
			panel_h += hint_gap + len(hint_lines) * meta_font.get_height() + max(0, len(hint_lines) - 1) * self._scaled_px(2)
		panel_h += padding_bottom
		panel_h = max(self._scaled_px(196), panel_h)
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

		line_top = panel_y + padding_top
		line2 = line_top + header_font.get_height() + line_gap
		line3 = line2 + name_font.get_height() + line_gap
		line4 = line3 + meta_font.get_height() + meta_gap
		screen.blit(header_font.render(header, True, (200, 220, 255)), (panel_x + self._scaled_px(12), line_top))
		screen.blit(name_font.render(str(name), True, (255, 255, 255)), (panel_x + self._scaled_px(12), line2))
		screen.blit(
			meta_font.render(f"置信度: {confidence_text}", True, (220, 220, 220)),
			(panel_x + self._scaled_px(12), line3),
		)
		screen.blit(
			meta_font.render(f"来源: {source_text}", True, (220, 220, 220)),
			(panel_x + self._scaled_px(12), line4),
		)

		if hint_lines:
			hint_y = line4 + meta_font.get_height() + hint_gap
			for index, hint_line in enumerate(hint_lines):
				hint_label = meta_font.render(str(hint_line), True, (236, 236, 236))
				screen.blit(
					hint_label,
					(panel_x + padding_x, hint_y + index * (meta_font.get_height() + self._scaled_px(2))),
				)

	def _draw_stats_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		meta_font = self._font_medium
		item_font = self._font_small if self._is_portrait_layout() else self._font_medium
		if pygame is None or screen is None or meta_font is None or item_font is None:
			return

		screen.fill((20, 24, 28))
		self._draw_centered_text("区域统计", y=self._scaled_px(12), size="medium")
		region = view_model.get("region_display_name") or view_model.get("region_id") or "<未选择>"
		region_y = self._scaled_px(44)
		screen.blit(meta_font.render(f"区域: {region}", True, (220, 220, 220)), (self._scaled_px(12), region_y))

		page = int(view_model.get("page", 0)) + 1
		total_pages = max(1, int(view_model.get("total_pages", 1)))
		page_y = region_y + meta_font.get_height() + self._scaled_px(4)
		screen.blit(meta_font.render(f"页码: {page}/{total_pages}", True, (220, 220, 220)), (self._scaled_px(12), page_y))

		error_message = view_model.get("stats_error_message")
		warning_y = page_y + meta_font.get_height() + self._scaled_px(4)
		if error_message:
			screen.blit(
				meta_font.render(f"警告: {error_message}", True, (240, 190, 70)),
				(self._scaled_px(12), warning_y),
			)

		items = view_model.get("items") or []
		items_start_y = warning_y + meta_font.get_height() + self._scaled_px(6) if error_message else warning_y
		row_h = item_font.get_height() + self._scaled_px(8)
		max_items = max(1, (self._height - items_start_y - self._scaled_px(30)) // row_h)
		if not items:
			screen.blit(item_font.render("暂无统计数据", True, (180, 180, 180)), (self._scaled_px(12), items_start_y))
		else:
			for index, item in enumerate(items[:max_items], start=1):
				name = item.get("display_name") or "<未知>"
				count = item.get("count")
				line = f"{index}. {name}  x{count}"
				screen.blit(
					item_font.render(line, True, (245, 245, 245)),
					(self._scaled_px(12), items_start_y + (index - 1) * row_h),
				)

	def _draw_map_stats_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		meta_font = self._font_small
		item_font = self._font_small if self._is_portrait_layout() else self._font_medium
		if pygame is None or screen is None or meta_font is None or item_font is None:
			return

		portrait = self._is_portrait_layout()
		screen.fill((18, 22, 26))
		self._draw_centered_text("地图统计", y=self._scaled_px(12), size="small" if portrait else "medium")

		thumb_width = self._scaled_px(92 if portrait else 112)
		thumb_height = self._scaled_px(68 if portrait else 72)

		thumb_surface = self._get_media_surface(
			view_model.get("map_thumbnail_path"),
			label=str(view_model.get("map_display_name") or view_model.get("map_id") or "地图"),
			width=thumb_width,
			height=thumb_height,
			cover=False,
		)
		thumb_x = self._width - thumb_width - self._scaled_px(12)
		thumb_y = self._scaled_px(42)
		if thumb_surface is not None:
			screen.blit(thumb_surface, (thumb_x, thumb_y))

		map_name = view_model.get("map_display_name") or view_model.get("map_id") or "<未选择>"
		text_x = self._scaled_px(12)
		text_y = self._scaled_px(46)
		text_max_width = max(self._scaled_px(120), thumb_x - text_x - self._scaled_px(12))
		self._blit_text(
			f"地图: {map_name}",
			font=item_font,
			x=text_x,
			y=text_y,
			max_width=text_max_width,
			max_lines=1,
		)
		summary_y = text_y + item_font.get_height() + self._scaled_px(6)
		for summary_line in (
			f"区域总数: {view_model.get('total_region_count', 0)}",
			f"已记录区域: {view_model.get('recorded_region_count', 0)}",
			f"植物种类: {view_model.get('plant_species_count', 0)}",
		):
			self._blit_text(summary_line, font=meta_font, x=text_x, y=summary_y, color=(220, 220, 220), max_width=text_max_width, max_lines=1)
			summary_y += meta_font.get_height() + self._scaled_px(4)

		page = int(view_model.get("page", 0)) + 1
		total_pages = max(1, int(view_model.get("total_pages", 1)))
		page_y = max(summary_y + self._scaled_px(6), thumb_y + thumb_height + self._scaled_px(8))
		self._blit_text(f"页码: {page}/{total_pages}", font=meta_font, x=text_x, y=page_y, color=(220, 220, 220))

		error_message = view_model.get("map_stats_error_message")
		warning_y = page_y + meta_font.get_height() + self._scaled_px(4)
		if error_message:
			self._blit_text(f"警告: {error_message}", font=meta_font, x=text_x, y=warning_y, color=(240, 190, 70))

		items = view_model.get("items") or []
		items_start_y = warning_y + meta_font.get_height() + self._scaled_px(8) if error_message else warning_y
		row_h = item_font.get_height() + meta_font.get_height() * 2 + self._scaled_px(16)
		max_items = max(1, (self._height - items_start_y - self._scaled_px(30)) // row_h)
		if not items:
			self._blit_text("暂无地图统计", font=item_font, x=text_x, y=items_start_y, color=(180, 180, 180))
		else:
			for index, item in enumerate(items[:max_items], start=1):
				name = item.get("display_name") or "<未知>"
				total_count = item.get("total_count")
				covered = item.get("covered_region_count")
				covered_regions_text = str(item.get("covered_regions_text") or "")
				line_y = items_start_y + (index - 1) * row_h
				self._blit_text(
					f"{index}. {name}  x{total_count}",
					font=item_font,
					x=text_x,
					y=line_y,
					max_width=self._width - text_x - self._scaled_px(12),
					max_lines=1,
				)
				self._blit_text(
					f"覆盖区域: {covered}    所属区域: {covered_regions_text or '-'}",
					font=meta_font,
					x=text_x,
					y=line_y + item_font.get_height() + self._scaled_px(4),
					color=(214, 224, 240),
					max_width=self._width - text_x - self._scaled_px(12),
					max_lines=2,
				)

	def _draw_error_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		head_font = self._font_large
		body_font = self._font_medium
		if pygame is None or screen is None or head_font is None or body_font is None:
			return

		screen.fill((45, 8, 8))
		self._draw_centered_text("错误", y=self._scaled_px(14), size="large")
		error_type = view_model.get("error_type") or "UnknownError"
		error_message = view_model.get("error_message") or "no details"
		retryable = bool(view_model.get("retryable"))

		error_y = int(self._height * 0.34)
		screen.blit(head_font.render(str(error_type), True, (255, 230, 230)), (self._scaled_px(16), error_y))
		screen.blit(
			body_font.render(str(error_message), True, (255, 210, 210)),
			(self._scaled_px(16), error_y + head_font.get_height() + self._scaled_px(10)),
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
		self._draw_centered_text(text, y=self._height // 2 - self._scaled_px(6))

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
		return

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

	def _blit_text(
		self,
		text: str,
		*,
		font,
		x: int,
		y: int,
		color: tuple[int, int, int] = (245, 245, 245),
		max_width: int | None = None,
		max_lines: int = 2,
	) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None or font is None:
			return

		lines = [text]
		if max_width is not None:
			lines = self._wrap_text(font=font, text=text, max_width=max_width, max_lines=max_lines)

		for index, line in enumerate(lines):
			label = font.render(line, True, color)
			screen.blit(label, (x, y + index * (font.get_height() + self._scaled_px(2))))

	def _resolve_ui_scale(self) -> float:
		if self._ui_scale_override:
			try:
				return min(2.0, max(0.85, float(self._ui_scale_override)))
			except ValueError:
				pass
		return 1.0 if self._is_portrait_layout() else 1.25

	def _is_portrait_layout(self) -> bool:
		return self._height > self._width

	def _hint_lines(self, hint: Any, *, max_lines: int) -> list[str]:
		if not hint:
			return []

		font = self._font_small
		if font is None:
			return [str(hint)]

		max_width = max(self._scaled_px(120), self._width - self._scaled_px(32))
		return self._wrap_text(font=font, text=str(hint), max_width=max_width, max_lines=max_lines)

	def _hint_block_height(self, hint: Any, *, max_lines: int) -> int:
		font = self._font_small
		if font is None:
			return self._scaled_px(36)

		lines = self._hint_lines(hint, max_lines=max_lines) or [""]
		spacing = self._scaled_px(2)
		return self._scaled_px(12) + len(lines) * font.get_height() + max(0, len(lines) - 1) * spacing

	def _thumbnail_label_height(self) -> int:
		font = self._font_small
		if font is None:
			return self._scaled_px(28)
		return max(self._scaled_px(28), font.get_height() + self._scaled_px(8))

	def _draw_preview_result_source(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		font = self._font_small
		if pygame is None or screen is None or font is None:
			return

		source_name = str(view_model.get("last_recognition_source_display_name") or "").strip()
		if not source_name:
			return

		result_name = str(view_model.get("last_recognition_display_name") or "未识别").strip() or "未识别"
		lines = [f"上次结果: {result_name}", f"来源: {source_name}"]
		line_h = font.get_height()
		spacing = self._scaled_px(2)
		pad_x = self._scaled_px(10)
		pad_y = self._scaled_px(6)
		panel_w = max(font.size(line)[0] for line in lines) + pad_x * 2
		panel_h = pad_y * 2 + len(lines) * line_h + spacing
		panel_x = self._width - panel_w - self._scaled_px(12)
		panel_y = self._scaled_px(12)

		panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
		panel.fill((0, 0, 0, 165))
		screen.blit(panel, (panel_x, panel_y))

		if source_name == "云端":
			border_color = (88, 170, 255)
		elif source_name == "本地回退":
			border_color = (255, 190, 80)
		else:
			border_color = (88, 214, 148)
		pygame.draw.rect(screen, border_color, pygame.Rect(panel_x, panel_y, panel_w, panel_h), 2, border_radius=self._scaled_px(8))

		for index, line in enumerate(lines):
			label = font.render(line, True, (245, 245, 245))
			screen.blit(label, (panel_x + pad_x, panel_y + pad_y + index * (line_h + spacing)))

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
