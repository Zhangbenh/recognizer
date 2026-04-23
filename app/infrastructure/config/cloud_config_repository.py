"""Repository for cloud_config.json with environment override support."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from domain.errors import CloudConfigError


DEFAULT_BAIDU_TOKEN_ENDPOINT = "https://aip.baidubce.com/oauth/2.0/token"


@dataclass(frozen=True)
class CloudConfig:
	"""Resolved cloud configuration for the Baidu client."""

	version: str
	baidu_api_endpoint: str
	baidu_token_endpoint: str
	token_cache_file: Path
	request_timeout_s: float
	retry_count: int
	api_key: str | None = None
	secret_key: str | None = None
	api_key_env_name: str | None = None
	secret_key_env_name: str | None = None

	def require_credentials(self) -> tuple[str, str]:
		if not self.api_key or not self.secret_key:
			raise CloudConfigError("baidu api credentials are not configured", retryable=False)
		return self.api_key, self.secret_key


class CloudConfigRepository:
	"""Load and resolve cloud_config.json."""

	def __init__(
		self,
		file_path: str | None = None,
		*,
		environ: Mapping[str, str] | None = None,
	) -> None:
		self._file_path = Path(file_path) if file_path else self._default_file_path()
		self._environ = os.environ if environ is None else environ

	@property
	def file_path(self) -> Path:
		return self._file_path

	def load(self) -> CloudConfig:
		payload = self._read_json()

		api_key, api_key_env_name = self._resolve_sensitive_value(
			direct_env_key="RECOGNIZER_BAIDU_API_KEY",
			selector_env_key="RECOGNIZER_BAIDU_API_KEY_ENV",
			configured_env_name=payload.get("api_key_env"),
		)
		secret_key, secret_key_env_name = self._resolve_sensitive_value(
			direct_env_key="RECOGNIZER_BAIDU_SECRET_KEY",
			selector_env_key="RECOGNIZER_BAIDU_SECRET_KEY_ENV",
			configured_env_name=payload.get("secret_key_env"),
		)

		baidu_api_endpoint = self._resolve_string(
			field_name="baidu_api_endpoint",
			payload=payload,
			env_key="RECOGNIZER_BAIDU_API_ENDPOINT",
		)
		baidu_token_endpoint = self._resolve_string(
			field_name="baidu_token_endpoint",
			payload=payload,
			env_key="RECOGNIZER_BAIDU_TOKEN_ENDPOINT",
			default=DEFAULT_BAIDU_TOKEN_ENDPOINT,
		)
		request_timeout_s = self._resolve_float(
			field_name="request_timeout_s",
			payload=payload,
			env_key="RECOGNIZER_BAIDU_REQUEST_TIMEOUT_S",
			default=3.0,
		)
		retry_count = self._resolve_int(
			field_name="retry_count",
			payload=payload,
			env_key="RECOGNIZER_BAIDU_RETRY_COUNT",
			default=1,
		)
		token_cache_file_value = self._resolve_string(
			field_name="token_cache_file",
			payload=payload,
			env_key="RECOGNIZER_BAIDU_TOKEN_CACHE_FILE",
			default="data/.baidu_token_cache.json",
		)

		return CloudConfig(
			version=str(payload.get("version", "1.1.0")),
			baidu_api_endpoint=baidu_api_endpoint,
			baidu_token_endpoint=baidu_token_endpoint,
			token_cache_file=self._resolve_path(token_cache_file_value),
			request_timeout_s=request_timeout_s,
			retry_count=retry_count,
			api_key=api_key,
			secret_key=secret_key,
			api_key_env_name=api_key_env_name,
			secret_key_env_name=secret_key_env_name,
		)

	def _read_json(self) -> dict[str, Any]:
		if not self._file_path.exists():
			raise CloudConfigError(f"cloud config not found: {self._file_path}", retryable=True)

		try:
			with self._file_path.open("r", encoding="utf-8") as file:
				payload = json.load(file)
		except Exception as exc:
			raise CloudConfigError(f"cloud config is invalid: {exc}", retryable=True) from exc

		if not isinstance(payload, dict):
			raise CloudConfigError("cloud_config.json root must be an object", retryable=True)
		return payload

	def _resolve_sensitive_value(
		self,
		*,
		direct_env_key: str,
		selector_env_key: str,
		configured_env_name: Any,
	) -> tuple[str | None, str | None]:
		direct_value = self._env_value(direct_env_key)
		if direct_value is not None:
			return direct_value, direct_env_key

		selected_env_name = self._env_value(selector_env_key)
		if selected_env_name is not None:
			selected_value = self._env_value(selected_env_name)
			if selected_value is None:
				raise CloudConfigError(
					f"environment variable '{selected_env_name}' referenced by '{selector_env_key}' is not set",
					retryable=False,
				)
			return selected_value, selected_env_name

		configured_name = str(configured_env_name).strip() if configured_env_name is not None else None
		if configured_name:
			configured_value = self._env_value(configured_name)
			if configured_value is not None:
				return configured_value, configured_name

		return None, configured_name

	def _resolve_string(
		self,
		*,
		field_name: str,
		payload: dict[str, Any],
		env_key: str,
		default: str | None = None,
	) -> str:
		env_value = self._env_value(env_key)
		if env_value is not None:
			return env_value

		value = payload.get(field_name, default)
		if not isinstance(value, str) or not value.strip():
			raise CloudConfigError(
				f"cloud_config.json field '{field_name}' must be a non-empty string",
				retryable=True,
			)
		return value.strip()

	def _resolve_float(
		self,
		*,
		field_name: str,
		payload: dict[str, Any],
		env_key: str,
		default: float,
	) -> float:
		value = self._env_value(env_key)
		if value is None:
			value = payload.get(field_name, default)
		try:
			result = float(value)
		except (TypeError, ValueError) as exc:
			raise CloudConfigError(
				f"cloud_config.json field '{field_name}' must be a float-compatible value",
				retryable=True,
			) from exc
		if result <= 0:
			raise CloudConfigError(
				f"cloud_config.json field '{field_name}' must be > 0",
				retryable=True,
			)
		return result

	def _resolve_int(
		self,
		*,
		field_name: str,
		payload: dict[str, Any],
		env_key: str,
		default: int,
	) -> int:
		value = self._env_value(env_key)
		if value is None:
			value = payload.get(field_name, default)
		try:
			result = int(value)
		except (TypeError, ValueError) as exc:
			raise CloudConfigError(
				f"cloud_config.json field '{field_name}' must be an int-compatible value",
				retryable=True,
			) from exc
		if result < 0:
			raise CloudConfigError(
				f"cloud_config.json field '{field_name}' must be >= 0",
				retryable=True,
			)
		return result

	def _resolve_path(self, raw_value: str) -> Path:
		path = Path(raw_value)
		if path.is_absolute():
			return path

		base_dir = self._file_path.parent
		if base_dir.name == "config":
			base_dir = base_dir.parent
		return (base_dir / path).resolve()

	def _env_value(self, key: str) -> str | None:
		value = self._environ.get(key)
		if value is None:
			return None
		stripped = str(value).strip()
		return stripped or None

	@staticmethod
	def _default_file_path() -> Path:
		return Path(__file__).resolve().parents[3] / "config" / "cloud_config.json"