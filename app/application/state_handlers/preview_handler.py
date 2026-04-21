"""PREVIEW state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.errors import CameraError, DataError, InferenceError, StorageError


def _is_preview_non_fatal(error_type: str | None) -> bool:
	if not error_type:
		return False
	return error_type in {
		CameraError.__name__,
		InferenceError.__name__,
		StorageError.__name__,
		DataError.__name__,
	}


class PreviewHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.PREVIEW)

	def on_enter(self, ctx: StateContext):
		# Keep camera chain alive in adapter layer; here we only reset transient
		# display data that should not leak into next recognition turn.
		ctx.current_stats_snapshot = None

		if ctx.preview_error_flash_pending:
			# First PREVIEW entry after a non-fatal failure: keep error for one render.
			return []
		elif ctx.last_error and _is_preview_non_fatal(ctx.last_error.error_type):
			# Next PREVIEW entry: clear previously surfaced non-fatal error.
			ctx.clear_error()
		return []

