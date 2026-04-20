"""Domain service for release-gate checks before runtime starts."""

from __future__ import annotations

from typing import Any

from domain.errors import ModelError
from infrastructure.config.model_manifest_repository import ModelManifestRepository
from infrastructure.config.system_config_repository import SystemConfigRepository


class ReleaseGateService:
	"""Validate model quality/contracts required by system config."""

	def __init__(
		self,
		*,
		model_manifest_repository: ModelManifestRepository,
		system_config_repository: SystemConfigRepository,
	) -> None:
		self._model_manifest_repository = model_manifest_repository
		self._system_config_repository = system_config_repository

	def criteria(self) -> tuple[float, int]:
		release_gate = self._system_config_repository.release_gate()
		min_top1 = float(release_gate.get("min_top1_accuracy", 0.0))
		required_classes = int(release_gate.get("required_output_classes", 0))
		return min_top1, required_classes

	def check(self) -> bool:
		min_top1, required_classes = self.criteria()
		return self._model_manifest_repository.validate_release_gate(
			min_top1_accuracy=min_top1,
			required_output_classes=required_classes,
		)

	def ensure_pass(self) -> None:
		if self.check():
			return

		manifest = self._model_manifest_repository.load()
		min_top1, required_classes = self.criteria()

		actual_top1 = float(manifest.get("evaluated_top1_accuracy", 0.0))
		actual_classes = int(manifest.get("output_classes", -1))
		raise ModelError(
			(
				"release gate failed: "
				f"top1={actual_top1:.4f} required>={min_top1:.4f}, "
				f"classes={actual_classes} required={required_classes}"
			),
			retryable=False,
		)

