"""Centralized guard evaluation helpers."""

from __future__ import annotations

from application.state_context import StateContext
from domain.constants import HOME_OPTION_NORMAL, HOME_OPTION_SAMPLING, MODE_NORMAL, MODE_SAMPLING


class GuardEvaluator:
	"""Evaluate all documented guard predicates in one place."""

	def is_home_normal_selected(self, ctx: StateContext) -> bool:
		return ctx.selected_home_option == HOME_OPTION_NORMAL

	def is_home_sampling_selected(self, ctx: StateContext) -> bool:
		return ctx.selected_home_option == HOME_OPTION_SAMPLING

	def has_available_maps(self, ctx: StateContext) -> bool:
		return ctx.has_available_maps

	def has_available_regions(self, ctx: StateContext) -> bool:
		return ctx.has_available_regions

	def is_recognized(self, ctx: StateContext) -> bool:
		return ctx.is_recognized

	def is_unrecognized(self, ctx: StateContext) -> bool:
		return not ctx.is_recognized

	def is_retryable(self, ctx: StateContext) -> bool:
		return ctx.error_is_retryable

	def is_not_retryable(self, ctx: StateContext) -> bool:
		return not ctx.error_is_retryable

	def retry_success(self, ctx: StateContext) -> bool:
		return ctx.retry_success

	def retry_failed(self, ctx: StateContext) -> bool:
		return not ctx.retry_success

	def is_normal_mode(self, ctx: StateContext) -> bool:
		return ctx.mode == MODE_NORMAL

	def is_sampling_mode(self, ctx: StateContext) -> bool:
		return ctx.mode == MODE_SAMPLING

