from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

np = pytest.importorskip("numpy")

from controller.app_controller import _encode_frame_for_cloud

from infrastructure.cloud.baidu_plant_client import BaiduPlantClient, HttpResponse
from infrastructure.cloud.token_cache import BaiduTokenCache
from infrastructure.config.cloud_config_repository import CloudConfigRepository


class FakeTransport:
	def __init__(self) -> None:
		self.calls: list[dict[str, object]] = []

	def request(
		self,
		method: str,
		url: str,
		*,
		headers: dict[str, str] | None = None,
		data: bytes | None = None,
		timeout_s: float,
	) -> HttpResponse:
		self.calls.append(
			{
				"method": method,
				"url": url,
				"headers": headers or {},
				"data": data or b"",
				"timeout_s": timeout_s,
			}
		)
		if url.startswith("https://oauth.example.test/oauth/2.0/token"):
			return HttpResponse(
				status_code=200,
				headers={"Content-Type": "application/json"},
				body=json.dumps(
					{
						"access_token": "token-123",
						"expires_in": 3600,
						"scope": "brain_all_scope",
					}
				).encode("utf-8"),
			)
		return HttpResponse(
			status_code=200,
			headers={"Content-Type": "application/json"},
			body=json.dumps(
				{
					"log_id": 42,
					"result": [
						{
							"name": "香蕉",
							"score": 0.98,
						}
					],
				}
			).encode("utf-8"),
		)


def test_cloud_config_repository_prefers_direct_env_then_named_env_over_config(tmp_path, monkeypatch) -> None:
	config_path = tmp_path / "cloud_config.json"
	config_path.write_text(
		json.dumps(
			{
				"version": "1.1.0",
				"baidu_api_endpoint": "https://plant.example.test/rest/2.0/image-classify/v1/plant",
				"api_key": "literal-api-key",
				"secret_key": "literal-secret-key",
				"api_key_env": "CONFIG_API_KEY",
				"secret_key_env": "CONFIG_SECRET_KEY",
				"token_cache_file": "data/cache.json",
				"request_timeout_s": 3.0,
				"retry_count": 1,
			},
			ensure_ascii=False,
		),
		encoding="utf-8",
	)

	monkeypatch.setenv("CONFIG_API_KEY", "config-api-key")
	monkeypatch.setenv("CONFIG_SECRET_KEY", "config-secret-key")
	monkeypatch.setenv("ALT_SECRET_KEY", "named-secret-key")
	monkeypatch.setenv("RECOGNIZER_BAIDU_API_KEY_ENV", "ALT_API_KEY")
	monkeypatch.setenv("RECOGNIZER_BAIDU_SECRET_KEY_ENV", "ALT_SECRET_KEY")
	monkeypatch.setenv("ALT_API_KEY", "named-api-key")
	monkeypatch.setenv("RECOGNIZER_BAIDU_API_KEY", "direct-api-key")
	monkeypatch.setenv("RECOGNIZER_BAIDU_REQUEST_TIMEOUT_S", "4.5")
	monkeypatch.setenv("RECOGNIZER_BAIDU_RETRY_COUNT", "2")

	repo = CloudConfigRepository(file_path=str(config_path))
	config = repo.load()

	assert config.api_key == "direct-api-key"
	assert config.secret_key == "named-secret-key"
	assert config.api_key_env_name == "RECOGNIZER_BAIDU_API_KEY"
	assert config.secret_key_env_name == "ALT_SECRET_KEY"
	assert config.request_timeout_s == 4.5
	assert config.retry_count == 2
	assert config.baidu_token_endpoint == "https://aip.baidubce.com/oauth/2.0/token"
	assert config.token_cache_file == (tmp_path / "data" / "cache.json").resolve()


def test_cloud_config_repository_falls_back_to_literal_credentials(tmp_path) -> None:
	config_path = tmp_path / "cloud_config.json"
	config_path.write_text(
		json.dumps(
			{
				"version": "1.1.0",
				"baidu_api_endpoint": "https://plant.example.test/rest/2.0/image-classify/v1/plant",
				"baidu_token_endpoint": "https://oauth.example.test/oauth/2.0/token",
				"api_key": "literal-api-key",
				"secret_key": "literal-secret-key",
				"api_key_env": "BAIDU_API_KEY",
				"secret_key_env": "BAIDU_SECRET_KEY",
				"token_cache_file": "data/cache.json",
				"request_timeout_s": 3.0,
				"retry_count": 1,
			},
			ensure_ascii=False,
		),
		encoding="utf-8",
	)

	repo = CloudConfigRepository(file_path=str(config_path), environ={})
	config = repo.load()

	assert config.api_key == "literal-api-key"
	assert config.secret_key == "literal-secret-key"
	assert config.api_key_env_name == "cloud_config.json:api_key"
	assert config.secret_key_env_name == "cloud_config.json:secret_key"


def test_baidu_client_uses_token_cache_and_builds_form_request(tmp_path, monkeypatch) -> None:
	cache_path = tmp_path / "runtime" / ".baidu_token_cache.json"
	config_path = tmp_path / "cloud_config.json"
	config_path.write_text(
		json.dumps(
			{
				"version": "1.1.0",
				"baidu_api_endpoint": "https://plant.example.test/rest/2.0/image-classify/v1/plant",
				"baidu_token_endpoint": "https://oauth.example.test/oauth/2.0/token",
				"api_key_env": "BAIDU_API_KEY",
				"secret_key_env": "BAIDU_SECRET_KEY",
				"token_cache_file": str(cache_path),
				"request_timeout_s": 2.5,
				"retry_count": 1,
			},
			ensure_ascii=False,
		),
		encoding="utf-8",
	)
	monkeypatch.setenv("BAIDU_API_KEY", "api-key")
	monkeypatch.setenv("BAIDU_SECRET_KEY", "secret-key")

	repo = CloudConfigRepository(file_path=str(config_path))
	transport = FakeTransport()
	client = BaiduPlantClient(
		config_repository=repo,
		transport=transport,
		clock=lambda: 1000.0,
	)

	first = client.recognize_image_bytes(b"\x89PNG", baike_num=1)
	second = client.recognize_image_bytes(b"\x89PNG", baike_num=1)

	assert first.log_id == 42
	assert second.candidates[0].name == "香蕉"
	assert first.candidates[0].score == 0.98

	token_calls = [call for call in transport.calls if str(call["url"]).startswith("https://oauth.example.test/")]
	plant_calls = [call for call in transport.calls if str(call["url"]).startswith("https://plant.example.test/")]
	assert len(token_calls) == 1
	assert len(plant_calls) == 2

	plant_url = urlparse(str(plant_calls[0]["url"]))
	assert parse_qs(plant_url.query)["access_token"] == ["token-123"]
	plant_body = parse_qs(bytes(plant_calls[0]["data"]).decode("utf-8"))
	assert plant_body["image"] == ["iVBORw=="]
	assert plant_body["baike_num"] == ["1"]
	assert plant_calls[0]["headers"] == {"Content-Type": "application/x-www-form-urlencoded"}
	assert plant_calls[0]["timeout_s"] == 2.5

	cache = BaiduTokenCache(cache_path, clock=lambda: 1000.0)
	assert cache.get_valid() is not None
	assert cache.get_valid().access_token == "token-123"


def test_cloud_frame_encoder_supports_numpy_without_pillow_dependency() -> None:
	frame = np.array(
		[
			[[255, 0, 0], [0, 255, 0]],
			[[0, 0, 255], [255, 255, 255]],
		],
		dtype=np.uint8,
	)

	encoded = _encode_frame_for_cloud(frame)

	assert encoded[:2] == b"BM"
	assert len(encoded) > 54