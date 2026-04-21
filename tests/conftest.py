from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
if str(APP_DIR) not in sys.path:
	sys.path.insert(0, str(APP_DIR))


import main as app_main
from infrastructure.logging.logger import create_logger


@pytest.fixture
def mock_controller():
	logger = create_logger(name="recognizer.tests", level="ERROR")
	controller = app_main.build_controller(
		runtime_backend="mock",
		input_backend="keyboard",
		ui_backend="text",
		logger=logger,
	)
	try:
		yield controller
	finally:
		controller.stop()
