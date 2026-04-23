"""Scaffolding client for Baidu plant recognition."""

from __future__ import annotations

import base64
import json
import socket
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib import error, parse, request

from domain.errors import CloudAuthError, CloudConfigError, CloudRecognitionError, CloudTimeoutError
from infrastructure.cloud.token_cache import BaiduTokenCache
from infrastructure.config.cloud_config_repository import CloudConfig, CloudConfigRepository


@dataclass(frozen=True)
class HttpResponse:
	"""Minimal HTTP response contract used by the Baidu client."""

	status_code: int
	headers: dict[str, str]
	body: bytes


class HttpTransport(Protocol):
	"""Transport abstraction for testable HTTP requests."""

	def request(
		self,
		method: str,
		url: str,
		*,
		headers: dict[str, str] | None = None,
		data: bytes | None = None,
		timeout_s: float,
	) -> HttpResponse:
		...


class UrllibHttpTransport:
	"""Standard-library HTTP transport implementation."""

	def request(
		self,
		method: str,
		url: str,
		*,
		headers: dict[str, str] | None = None,
		data: bytes | None = None,
		timeout_s: float,
	) -> HttpResponse:
		request_object = request.Request(
			url=url,
			data=data,
			headers=headers or {},
			method=method.upper(),
		)
		try:
			with request.urlopen(request_object, timeout=timeout_s) as response:
				status_code = getattr(response, "status", response.getcode())
				return HttpResponse(
					status_code=int(status_code),
					headers=dict(response.headers.items()),
					body=response.read(),
				)
		except error.HTTPError as exc:
			return HttpResponse(
				status_code=int(exc.code),
				headers=dict(exc.headers.items()),
				body=exc.read(),
			)
		except error.URLError as exc:
			reason = exc.reason
			if isinstance(reason, (TimeoutError, socket.timeout)):
				raise CloudTimeoutError("baidu request timed out", retryable=True) from exc
			raise CloudRecognitionError(f"baidu request failed: {exc}", retryable=True) from exc


@dataclass(frozen=True)
class BaiduPlantCandidate:
	"""A single Baidu plant recognition candidate."""

	name: str
	score: float
	baike_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class BaiduPlantResponse:
	"""Parsed Baidu plant recognition response."""

	log_id: int | None
	candidates: list[BaiduPlantCandidate]
	raw_payload: dict[str, Any]


class BaiduPlantClient:
	"""Small Baidu plant client that is safe to wire later into runtime."""

	def __init__(
		self,
		config_repository: CloudConfigRepository,
		*,
		transport: HttpTransport | None = None,
		token_cache: BaiduTokenCache | None = None,
		clock: Callable[[], float] | None = None,
	) -> None:
		self._config_repository = config_repository
		self._transport = transport or UrllibHttpTransport()
		self._clock = clock
		self._token_cache = token_cache

	def recognize_image_bytes(self, image_bytes: bytes, *, baike_num: int = 0) -> BaiduPlantResponse:
		if not image_bytes:
			raise CloudRecognitionError("image bytes are empty", retryable=False)

		config = self._config_repository.load()
		token_cache = self._get_token_cache(config)
		access_token = self._get_access_token(config, token_cache=token_cache)

		for attempt in range(config.retry_count + 1):
			response = self._perform_recognition_request(
				config=config,
				access_token=access_token,
				image_bytes=image_bytes,
				baike_num=baike_num,
			)
			payload = self._decode_payload(response.body, context="baidu plant response")

			if response.status_code >= 400:
				raise CloudRecognitionError(
					f"baidu plant request failed with status {response.status_code}",
					retryable=response.status_code >= 500,
				)

			error_code = payload.get("error_code")
			if error_code is not None:
				if str(error_code) in {"110", "111"} and attempt < config.retry_count:
					token_cache.clear()
					access_token = self._get_access_token(config, token_cache=token_cache, force_refresh=True)
					continue
				raise CloudRecognitionError(
					f"baidu plant request returned error_code={error_code}: {payload.get('error_msg', 'unknown error')}",
					retryable=True,
				)

			return self._parse_recognition_payload(payload)

		raise CloudRecognitionError("baidu plant request exhausted retries", retryable=True)

	def _get_access_token(
		self,
		config: CloudConfig,
		*,
		token_cache: BaiduTokenCache,
		force_refresh: bool = False,
	) -> str:
		if not force_refresh:
			cached = token_cache.get_valid()
			if cached is not None:
				return cached.access_token

		api_key, secret_key = config.require_credentials()
		request_body = parse.urlencode(
			{
				"grant_type": "client_credentials",
				"client_id": api_key,
				"client_secret": secret_key,
			}
		).encode("utf-8")

		response = self._send_request(
			method="POST",
			url=config.baidu_token_endpoint,
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			data=request_body,
			timeout_s=config.request_timeout_s,
			context="baidu token request",
		)
		payload = self._decode_payload(response.body, context="baidu token response")

		if response.status_code >= 400:
			raise CloudAuthError(
				f"baidu token request failed with status {response.status_code}",
				retryable=response.status_code >= 500,
			)

		if payload.get("error") is not None:
			raise CloudAuthError(
				f"baidu token request returned error: {payload.get('error_description', payload['error'])}",
				retryable=True,
			)

		access_token = payload.get("access_token")
		expires_in = payload.get("expires_in")
		if not isinstance(access_token, str) or not access_token.strip():
			raise CloudAuthError("baidu token response missing access_token", retryable=True)
		try:
			expires_in_value = int(expires_in)
		except (TypeError, ValueError) as exc:
			raise CloudAuthError("baidu token response missing valid expires_in", retryable=True) from exc

		scope = payload.get("scope")
		token_cache.save(
			access_token=access_token.strip(),
			expires_at=self._now() + expires_in_value,
			scope=str(scope).strip() if scope else None,
		)
		return access_token.strip()

	def _perform_recognition_request(
		self,
		*,
		config: CloudConfig,
		access_token: str,
		image_bytes: bytes,
		baike_num: int,
	) -> HttpResponse:
		encoded_image = base64.b64encode(image_bytes).decode("ascii")
		request_fields: dict[str, str] = {"image": encoded_image}
		if baike_num > 0:
			request_fields["baike_num"] = str(int(baike_num))
		request_body = parse.urlencode(request_fields).encode("utf-8")

		request_url = (
			f"{config.baidu_api_endpoint}?"
			f"{parse.urlencode({'access_token': access_token})}"
		)
		return self._send_request(
			method="POST",
			url=request_url,
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			data=request_body,
			timeout_s=config.request_timeout_s,
			context="baidu plant request",
		)

	def _send_request(
		self,
		*,
		method: str,
		url: str,
		headers: dict[str, str],
		data: bytes,
		timeout_s: float,
		context: str,
	) -> HttpResponse:
		try:
			return self._transport.request(
				method,
				url,
				headers=headers,
				data=data,
				timeout_s=timeout_s,
			)
		except CloudTimeoutError:
			raise
		except CloudRecognitionError:
			raise
		except CloudConfigError:
			raise
		except Exception as exc:
			raise CloudRecognitionError(f"{context} failed: {exc}", retryable=True) from exc

	def _parse_recognition_payload(self, payload: dict[str, Any]) -> BaiduPlantResponse:
		results = payload.get("result", [])
		if not isinstance(results, list):
			raise CloudRecognitionError("baidu plant response field 'result' must be a list", retryable=True)

		candidates: list[BaiduPlantCandidate] = []
		for item in results:
			if not isinstance(item, dict):
				continue
			name = item.get("name")
			score = item.get("score")
			if not isinstance(name, str):
				continue
			try:
				score_value = float(score)
			except (TypeError, ValueError):
				continue
			baike_info = item.get("baike_info")
			candidates.append(
				BaiduPlantCandidate(
					name=name,
					score=score_value,
					baike_info=baike_info if isinstance(baike_info, dict) else None,
				)
			)

		log_id_raw = payload.get("log_id")
		try:
			log_id = int(log_id_raw) if log_id_raw is not None else None
		except (TypeError, ValueError):
			log_id = None

		return BaiduPlantResponse(log_id=log_id, candidates=candidates, raw_payload=payload)

	def _decode_payload(self, body: bytes, *, context: str) -> dict[str, Any]:
		try:
			payload = json.loads(body.decode("utf-8"))
		except Exception as exc:
			raise CloudRecognitionError(f"{context} is not valid JSON: {exc}", retryable=True) from exc
		if not isinstance(payload, dict):
			raise CloudRecognitionError(f"{context} root must be an object", retryable=True)
		return payload

	def _get_token_cache(self, config: CloudConfig) -> BaiduTokenCache:
		if self._token_cache is None or self._token_cache.file_path != config.token_cache_file:
			self._token_cache = BaiduTokenCache(
				config.token_cache_file,
				clock=self._clock,
			)
		return self._token_cache

	def _now(self) -> float:
		if self._clock is None:
			from time import time

			return time()
		return self._clock()