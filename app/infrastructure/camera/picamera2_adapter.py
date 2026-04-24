"""Picamera2 implementation of camera adapter."""

from __future__ import annotations

import time
from typing import Any

from infrastructure.camera.base_camera_adapter import BaseCameraAdapter


class Picamera2Adapter(BaseCameraAdapter):
	"""Camera adapter backed by Picamera2 on Raspberry Pi."""

	def __init__(
		self,
		*,
		width: int = 960,
		height: int = 540,
		rotation: int = 90,
		swap_red_blue: bool = True,
		warmup_seconds: float = 0.5,
	) -> None:
		self._width = width
		self._height = height
		self._rotation = rotation
		self._swap_red_blue = swap_red_blue
		self._warmup_seconds = warmup_seconds

		self._camera: Any = None
		self._started = False

	@property
	def is_started(self) -> bool:
		return self._started

	def start(self) -> None:
		if self._started:
			return

		try:
			from picamera2 import Picamera2
		except ImportError as exc:
			raise RuntimeError(
				"picamera2 is not available. Install python3-picamera2 on Raspberry Pi."
			) from exc

		self._camera = Picamera2()
		preview_config = self._camera.create_preview_configuration(
			main={"size": (self._width, self._height), "format": "RGB888"}
		)
		self._camera.configure(preview_config)
		self._camera.start()
		time.sleep(self._warmup_seconds)
		self._started = True

	def stop(self) -> None:
		if not self._started:
			return
		if self._camera is not None:
			self._camera.stop()
		self._started = False

	def capture_frame(self):
		if not self._started or self._camera is None:
			raise RuntimeError("camera is not started")

		frame = self._camera.capture_array()

		if self._swap_red_blue:
			frame = frame[:, :, [2, 1, 0]]

		if self._rotation in {90, 180, 270}:
			import numpy as np

			if self._rotation == 90:
				frame = np.rot90(frame, k=1)
			elif self._rotation == 180:
				frame = np.rot90(frame, k=2)
			elif self._rotation == 270:
				frame = np.rot90(frame, k=3)

		return frame

	def close(self) -> None:
		try:
			self.stop()
		finally:
			if self._camera is not None:
				self._camera.close()
			self._camera = None

