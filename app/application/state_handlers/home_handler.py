"""HOME state handler."""

from __future__ import annotations

from application.state_context import StateContext
from application.state_handlers.base_handler import BaseStateHandler
from application.states import State
from domain.constants import HOME_OPTION_NORMAL


class HomeHandler(BaseStateHandler):
	def __init__(self) -> None:
		super().__init__(State.HOME)

	def on_enter(self, ctx: StateContext):
		if ctx.home_option_dirty:
			# HOME self-loop navigation should keep the toggled option for this render.
			ctx.home_option_dirty = False
		else:
			ctx.selected_home_option = HOME_OPTION_NORMAL
		ctx.clear_flow_transients()
		# HOME is the neutral safe page; clear non-fatal residual errors.
		ctx.clear_error()
		return []

