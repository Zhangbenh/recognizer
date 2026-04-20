"""Pure domain rules for recognition decisions and value normalization."""

from __future__ import annotations


def clamp_probability(value: float) -> float:
	if value < 0.0:
		return 0.0
	if value > 1.0:
		return 1.0
	return value


def normalize_threshold(value: float) -> float:
	return clamp_probability(value)


def is_recognized(confidence: float, threshold: float) -> bool:
	return clamp_probability(confidence) >= normalize_threshold(threshold)

