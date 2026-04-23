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
			self._draw_centered_text("植物识别系统", y=self._height // 2 - self._scaled_px(28), size="large")
			self._draw_centered_text("启动中...", y=self._height // 2 + self._scaled_px(8))
		elif state == State.HOME:
			self._draw_menu(view_model=view_model)
		elif state == State.MAP_SELECT:
			self._draw_selection_gallery(
				title="地图选择",
				items=view_model.get("map_items") or [],
				selected_id=view_model.get("selected_map_id"),
				hint=str(view_model.get("hint") or ""),
				hero_title=view_model.get("selected_map_display_name") or "未选择地图",
				hero_subtitle=str(view_model.get("selected_map_id") or ""),
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

		self._draw_centered_text(title, y=self._scaled_px(10), size="medium")

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
		margin = self._scaled_px(12)
		hero_rect = pygame.Rect(
			margin,
			self._scaled_px(44),
			self._width - margin * 2,
			int(self._height * 0.54),
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
			hero_rect.bottom - self._scaled_px(42),
			hero_rect.width,
			self._scaled_px(42),
		)
		caption = pygame.Surface((caption_rect.width, caption_rect.height), pygame.SRCALPHA)
		caption.fill((0, 0, 0, 165))
		screen.blit(caption, caption_rect.topleft)
		self._blit_text(str(hero_title), font=self._font_medium, x=caption_rect.x + self._scaled_px(10), y=caption_rect.y + self._scaled_px(4))
		if hero_subtitle:
			self._blit_text(str(hero_subtitle), font=caption_font, x=caption_rect.x + self._scaled_px(10), y=caption_rect.y + self._scaled_px(22), color=(214, 224, 240))

		thumb_y = hero_rect.bottom + self._scaled_px(12)
		hint_reserve = self._scaled_px(42)
		thumb_h = max(self._scaled_px(54), self._height - thumb_y - hint_reserve)
		gap = self._scaled_px(8)
		thumb_width = max(
			self._scaled_px(72),
			(self._width - margin * 2 - gap * max(0, len(items) - 1)) // max(1, len(items)),
		)

		for index, item in enumerate(items):
			thumb_rect = pygame.Rect(
				margin + index * (thumb_width + gap),
				thumb_y,
				thumb_width,
				thumb_h,
			)
			self._draw_media_card(
				rect=thumb_rect,
				thumbnail_path=item.get("thumbnail_path"),
				label=str(item.get("display_name") or item.get("id") or ""),
				highlighted=index == selected_index,
				cover=False,
				show_label=True,
			)

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
			label_h = self._scaled_px(26)
			overlay = pygame.Surface((rect.width, label_h), pygame.SRCALPHA)
			overlay.fill((0, 0, 0, 165))
			screen.blit(overlay, (rect.x, rect.bottom - label_h))
			self._blit_text(label, font=self._font_small, x=rect.x + self._scaled_px(6), y=rect.bottom - label_h + self._scaled_px(4), max_width=rect.width - self._scaled_px(12))

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
		if asset_path and asset_path.exists():
			try:
				loaded = pygame.image.load(str(asset_path))
				if loaded.get_alpha() is not None:
					loaded = loaded.convert_alpha()
				else:
					loaded = loaded.convert()
				fitted = self._fit_surface_to_box(loaded, width=width, height=height, cover=cover)
				surface.fill((16, 20, 26))
				surface.blit(fitted, fitted.get_rect(center=(width // 2, height // 2)))
			except Exception:
				surface = self._build_placeholder_surface(width=width, height=height, label=label)
		else:
			surface = self._build_placeholder_surface(width=width, height=height, label=label)

		self._image_cache[cache_key] = surface
		return surface

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

		lines = self._wrap_text(str(label or "未配置图片"), font=font, max_width=max(20, width - self._scaled_px(20)), max_lines=3)
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

		name = view_model.get("display_name") or "未识别"
		confidence = view_model.get("confidence")
		if isinstance(confidence, float):
			confidence_text = f"{confidence * 100:.1f}%"
		else:
			confidence_text = "--"

		header = "记录中" if recording else "识别结果"
		line_top = panel_y + self._scaled_px(12)
		line_gap = self._scaled_px(10)
		line2 = line_top + header_font.get_height() + line_gap
		line3 = line2 + name_font.get_height() + line_gap
		screen.blit(header_font.render(header, True, (200, 220, 255)), (panel_x + self._scaled_px(12), line_top))
		screen.blit(name_font.render(str(name), True, (255, 255, 255)), (panel_x + self._scaled_px(12), line2))
		screen.blit(
			meta_font.render(f"置信度: {confidence_text}", True, (220, 220, 220)),
			(panel_x + self._scaled_px(12), line3),
		)

		hint = "正在写入统计..." if recording else (view_model.get("hint") or "")
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

		hint_label = meta_font.render(str(view_model.get("hint") or ""), True, (236, 236, 236))
		screen.blit(
			hint_label,
			(self._scaled_px(8), self._height - hint_label.get_height() - self._scaled_px(6)),
		)

	def _draw_map_stats_panel(self, *, view_model: dict[str, Any]) -> None:
		pygame = self._pygame
		screen = self._screen
		meta_font = self._font_small
		item_font = self._font_medium
		if pygame is None or screen is None or meta_font is None or item_font is None:
			return

		screen.fill((18, 22, 26))
		self._draw_centered_text("地图统计", y=self._scaled_px(12), size="medium")

		thumb_surface = self._get_media_surface(
			view_model.get("map_thumbnail_path"),
			label=str(view_model.get("map_display_name") or view_model.get("map_id") or "地图"),
			width=self._scaled_px(112),
			height=self._scaled_px(72),
			cover=False,
		)
		if thumb_surface is not None:
			screen.blit(thumb_surface, (self._width - thumb_surface.get_width() - self._scaled_px(12), self._scaled_px(42)))

		map_name = view_model.get("map_display_name") or view_model.get("map_id") or "<未选择>"
		text_x = self._scaled_px(12)
		text_y = self._scaled_px(46)
		self._blit_text(f"地图: {map_name}", font=item_font, x=text_x, y=text_y)
		self._blit_text(f"区域总数: {view_model.get('total_region_count', 0)}", font=meta_font, x=text_x, y=text_y + item_font.get_height() + self._scaled_px(6), color=(220, 220, 220))
		self._blit_text(f"已记录区域: {view_model.get('recorded_region_count', 0)}", font=meta_font, x=text_x, y=text_y + item_font.get_height() + meta_font.get_height() + self._scaled_px(10), color=(220, 220, 220))
		self._blit_text(f"植物种类: {view_model.get('plant_species_count', 0)}", font=meta_font, x=text_x, y=text_y + item_font.get_height() + meta_font.get_height() * 2 + self._scaled_px(14), color=(220, 220, 220))

		page = int(view_model.get("page", 0)) + 1
		total_pages = max(1, int(view_model.get("total_pages", 1)))
		page_y = self._scaled_px(134)
		self._blit_text(f"页码: {page}/{total_pages}", font=meta_font, x=text_x, y=page_y, color=(220, 220, 220))

		error_message = view_model.get("map_stats_error_message")
		warning_y = page_y + meta_font.get_height() + self._scaled_px(4)
		if error_message:
			self._blit_text(f"警告: {error_message}", font=meta_font, x=text_x, y=warning_y, color=(240, 190, 70))

		items = view_model.get("items") or []
		items_start_y = warning_y + meta_font.get_height() + self._scaled_px(8) if error_message else warning_y
		row_h = item_font.get_height() + self._scaled_px(10)
		max_items = max(1, (self._height - items_start_y - self._scaled_px(30)) // row_h)
		if not items:
			self._blit_text("暂无地图统计", font=item_font, x=text_x, y=items_start_y, color=(180, 180, 180))
		else:
			for index, item in enumerate(items[:max_items], start=1):
				name = item.get("display_name") or "<未知>"
				total_count = item.get("total_count")
				covered = item.get("covered_region_count")
				line = f"{index}. {name}  x{total_count}  区域{covered}"
				self._blit_text(line, font=item_font, x=text_x, y=items_start_y + (index - 1) * row_h)

		hint_label = meta_font.render(str(view_model.get("hint") or ""), True, (236, 236, 236))
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
		action = "CONFIRM：重试" if retryable else "CONFIRM：忽略"
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

	def _blit_text(
		self,
		text: str,
		*,
		font,
		x: int,
		y: int,
		color: tuple[int, int, int] = (245, 245, 245),
		max_width: int | None = None,
	) -> None:
		pygame = self._pygame
		screen = self._screen
		if pygame is None or screen is None or font is None:
			return

		lines = [text]
		if max_width is not None:
			lines = self._wrap_text(font=font, text=text, max_width=max_width, max_lines=2)

		for index, line in enumerate(lines):
			label = font.render(line, True, color)
			screen.blit(label, (x, y + index * (font.get_height() + self._scaled_px(2))))

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
