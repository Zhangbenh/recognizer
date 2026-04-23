"""Recognizer application entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any
from controller.app_controller import AppController, build_app_controller
from infrastructure.logging.logger import create_logger
from infrastructure.storage.json_storage_adapter import JsonStorageAdapter


def default_input_backend() -> str:
	return "keyboard" if os.name == "nt" else "gpio"


def build_controller(
	*, runtime_backend: str, input_backend: str, ui_backend: str, logger: logging.Logger, **build_kwargs: Any
) -> AppController:
	storage_adapter_factory = build_kwargs.pop("storage_adapter_factory", JsonStorageAdapter)
	label_repository = build_kwargs.pop("label_repository", None)
	model_manifest_repository = build_kwargs.pop("model_manifest_repository", None)
	sampling_config_repository = build_kwargs.pop("sampling_config_repository", None)
	system_config_repository = build_kwargs.pop("system_config_repository", None)
	return build_app_controller(
		runtime_backend=runtime_backend,
		input_backend=input_backend,
		ui_backend=ui_backend,
		logger=logger,
		storage_adapter_factory=storage_adapter_factory,
		label_repository=label_repository,
		model_manifest_repository=model_manifest_repository,
		sampling_config_repository=sampling_config_repository,
		system_config_repository=system_config_repository,
		**build_kwargs,
	)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Plant recognizer runtime")
	parser.add_argument(
		"--runtime",
		choices=("real", "mock"),
		default=os.getenv("RECOGNIZER_RUNTIME", "real"),
		help="runtime backend (real uses camera+tflite, mock runs desktop-safe)",
	)
	parser.add_argument(
		"--input",
		choices=("keyboard", "gpio"),
		default=os.getenv("RECOGNIZER_INPUT", default_input_backend()),
		help="input backend",
	)
	parser.add_argument(
		"--ui-backend",
		choices=("text", "screen", "both"),
		default=os.getenv("RECOGNIZER_UI_BACKEND", "text"),
		help="ui backend: text logger, pygame screen, or both",
	)
	parser.add_argument("--max-ticks", type=int, default=None, help="optional max loop ticks for testing")
	parser.add_argument("--idle-sleep", type=float, default=0.02, help="sleep seconds when no work is done")
	parser.add_argument("--log-level", type=str, default=os.getenv("RECOGNIZER_LOG_LEVEL", "INFO"))
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	logger = create_logger(level=args.log_level)
	# Keep environment and runtime argument aligned for downstream components.
	os.environ["RECOGNIZER_UI_BACKEND"] = args.ui_backend
	controller = build_controller(
		runtime_backend=args.runtime,
		input_backend=args.input,
		ui_backend=args.ui_backend,
		logger=logger,
	)
	controller.run(max_ticks=args.max_ticks, idle_sleep_s=max(0.0, args.idle_sleep))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

