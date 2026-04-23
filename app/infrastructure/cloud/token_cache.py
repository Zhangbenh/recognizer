"""Persistent cache for Baidu access tokens."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CachedBaiduToken:
	"""Cached token metadata."""

	access_token: str
	expires_at: float
	scope: str | None = None

	def is_valid(self, now: float, *, expiry_skew_s: float = 60.0) -> bool:
		return bool(self.access_token) and (self.expires_at - now) > expiry_skew_s


class BaiduTokenCache:
	"""Read and write the local Baidu access token cache."""

	def __init__(
		self,
		file_path: str | Path,
		*,
		clock: Callable[[], float] | None = None,
		expiry_skew_s: float = 60.0,
	) -> None:
		self._file_path = Path(file_path)
		self._clock = clock or time.time
		self._expiry_skew_s = expiry_skew_s

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> CachedBaiduToken | None:
		if not self._file_path.exists():
			return None

		try:
			with self._file_path.open("r", encoding="utf-8") as file:
				payload = json.load(file)
		except Exception:
			return None

		if not isinstance(payload, dict):
			return None

		access_token = payload.get("access_token")
		expires_at = payload.get("expires_at")
		scope = payload.get("scope")
		if not isinstance(access_token, str) or not access_token.strip():
			return None
		try:
			expires_at_value = float(expires_at)
		except (TypeError, ValueError):
			return None
		if isinstance(scope, str):
			scope_value = scope.strip() or None
		else:
			scope_value = None
		return CachedBaiduToken(
			access_token=access_token.strip(),
			expires_at=expires_at_value,
			scope=scope_value,
		)

	def get_valid(self) -> CachedBaiduToken | None:
		cached = self.load()
		if cached and cached.is_valid(self._clock(), expiry_skew_s=self._expiry_skew_s):
			return cached
		return None

	def save(self, access_token: str, expires_at: float, *, scope: str | None = None) -> None:
		payload: dict[str, Any] = {
			"access_token": access_token,
			"expires_at": float(expires_at),
			"cached_at": float(self._clock()),
		}
		if scope:
			payload["scope"] = scope

		self._file_path.parent.mkdir(parents=True, exist_ok=True)
		temp_path = self._file_path.with_suffix(f"{self._file_path.suffix}.tmp")
		with temp_path.open("w", encoding="utf-8") as file:
			json.dump(payload, file, ensure_ascii=False, indent=2)
		temp_path.replace(self._file_path)

	def clear(self) -> None:
		if self._file_path.exists():
			self._file_path.unlink()