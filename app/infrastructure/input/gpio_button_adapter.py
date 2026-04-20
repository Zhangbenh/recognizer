"""GPIO button input adapter for Raspberry Pi."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from infrastructure.input.base_input_adapter import BaseInputAdapter


@dataclass(slots=True)
class _ButtonState:
	pin: int
	name: str
	long_press_ms: int
	debounce_ms: int
	pressed: bool = False
	press_ts: float = 0.0

	def update(self, gpio_module) -> tuple[str, float] | None:
		level = gpio_module.input(self.pin)

		if not self.pressed and level == gpio_module.LOW:
			time.sleep(self.debounce_ms / 1000.0)
			if gpio_module.input(self.pin) == gpio_module.LOW:
				self.pressed = True
				self.press_ts = time.monotonic()

		elif self.pressed and level == gpio_module.HIGH:
			duration_ms = (time.monotonic() - self.press_ts) * 1000.0
			self.pressed = False

			if duration_ms >= self.long_press_ms:
				return "LONG_PRESS", duration_ms
			return "SHORT_PRESS", duration_ms

		return None


class GPIOButtonAdapter(BaseInputAdapter):
	"""Poll GPIO inputs and emit BTNx_SHORT/BTNx_LONG raw events."""

	def __init__(
		self,
		*,
		btn1_pin: int = 17,
		btn2_pin: int = 18,
		long_press_ms: int = 800,
		debounce_ms: int = 300,
		poll_interval_s: float = 0.01,
		gpio_module: Optional[Any] = None,
	) -> None:
		self._poll_interval_s = poll_interval_s
		self._gpio = gpio_module
		self._initialized = False

		self._btn1 = _ButtonState(btn1_pin, "BTN1", long_press_ms, debounce_ms)
		self._btn2 = _ButtonState(btn2_pin, "BTN2", long_press_ms, debounce_ms)

	def poll_raw_inputs(self) -> list[dict[str, Any]]:
		self._ensure_initialized()

		events: list[dict[str, Any]] = []
		for button in (self._btn1, self._btn2):
			result = button.update(self._gpio)
			if not result:
				continue

			press_type, duration_ms = result
			events.append(
				{
					"event_type": f"{button.name}_{'LONG' if press_type == 'LONG_PRESS' else 'SHORT'}",
					"button": button.name,
					"press_type": press_type,
					"duration_ms": duration_ms,
					"source": "GPIOButtonAdapter",
				}
			)

		if self._poll_interval_s > 0:
			time.sleep(self._poll_interval_s)

		return events

	def close(self) -> None:
		if self._gpio is not None and self._initialized:
			self._gpio.cleanup()
		self._initialized = False

	def _ensure_initialized(self) -> None:
		if self._initialized:
			return

		if self._gpio is None:
			try:
				import RPi.GPIO as gpio
			except ImportError as exc:
				raise RuntimeError(
					"RPi.GPIO is not available. Install python3-rpi.gpio on Raspberry Pi."
				) from exc
			self._gpio = gpio

		self._gpio.setmode(self._gpio.BCM)
		self._gpio.setwarnings(False)
		self._gpio.setup(self._btn1.pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
		self._gpio.setup(self._btn2.pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
		self._initialized = True

