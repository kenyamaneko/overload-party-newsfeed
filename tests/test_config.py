import os
from unittest.mock import MagicMock, patch

import pytest

from newsfeed.config import load_config


def _base_env(**overrides) -> dict:
    env = {
        "GOOGLE_CLOUD_PROJECT": "my-project",
        "VERTEX_LOCATION": "us-central1",
    }
    env.update(overrides)
    return env


class TestLoadConfigRequired:
    def test_raises_when_google_cloud_project_missing(self):
        env = {"APP_ENV": "local", "VERTEX_LOCATION": "us-central1"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
                load_config()

    def test_raises_when_vertex_location_missing(self):
        env = {"APP_ENV": "local", "GOOGLE_CLOUD_PROJECT": "p"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="VERTEX_LOCATION"):
                load_config()

    def test_raises_when_app_env_missing(self):
        with patch.dict(os.environ, _base_env(), clear=True):
            with pytest.raises(ValueError, match="APP_ENV"):
                load_config()


class TestAppEnvValidation:
    def test_accepts_local(self):
        env = _base_env(APP_ENV="local", UPSTASH_REDIS_URL="redis://localhost:6379/0")
        with patch.dict(os.environ, env, clear=True):
            load_config()  # no raise

    @patch("newsfeed.config.SecretAccessor")
    def test_accepts_production(self, accessor_cls):
        accessor = MagicMock()
        accessor.access.side_effect = lambda sid: {
            "newsfeed-upstash-redis-endpoint": "upstash.example.com:6379",
            "newsfeed-upstash-redis-password": "s3cr3t",
        }[sid]
        accessor_cls.return_value = accessor

        env = _base_env(APP_ENV="production")
        with patch.dict(os.environ, env, clear=True):
            load_config()  # no raise

    def test_rejects_intermediate_values_like_dev_or_prod(self):
        """APP_ENV は local / production の 2 値のみ。dev / stg / prod は弾く
        (環境差分は GOOGLE_CLOUD_PROJECT で吸収する運用)。"""
        for invalid in ("dev", "stg", "prod", "staging", "test", ""):
            env = _base_env(APP_ENV=invalid)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ValueError, match="APP_ENV"):
                    load_config()


class TestLoadConfigLocalMode:
    def test_reads_upstash_url_from_env(self):
        env = _base_env(
            APP_ENV="local",
            UPSTASH_REDIS_URL="redis://localhost:6379/0",
        )
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            assert cfg.redis_url == "redis://localhost:6379/0"
            assert cfg.google_cloud_project == "my-project"
            assert cfg.vertex_location == "us-central1"

    def test_raises_when_upstash_url_missing_in_local(self):
        env = _base_env(APP_ENV="local")
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="UPSTASH_REDIS_URL"):
                load_config()


class TestLoadConfigProductionMode:
    @patch("newsfeed.config.SecretAccessor")
    def test_fetches_upstash_credentials_from_secret_manager(self, accessor_cls):
        accessor = MagicMock()
        accessor.access.side_effect = lambda sid: {
            "newsfeed-upstash-redis-endpoint": "upstash.example.com:6379",
            "newsfeed-upstash-redis-password": "s3cr3t",
        }[sid]
        accessor_cls.return_value = accessor

        env = _base_env(APP_ENV="production")
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()

        assert cfg.redis_url == "rediss://default:s3cr3t@upstash.example.com:6379"

    @patch("newsfeed.config.SecretAccessor")
    def test_url_encodes_password(self, accessor_cls):
        accessor = MagicMock()
        accessor.access.side_effect = lambda sid: {
            "newsfeed-upstash-redis-endpoint": "upstash.example.com:6379",
            "newsfeed-upstash-redis-password": "p@ss/w:rd",
        }[sid]
        accessor_cls.return_value = accessor

        env = _base_env(APP_ENV="production")
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()

        # @ / : は URL 予約文字でエンコードされる
        assert "p%40ss%2Fw%3Ard" in cfg.redis_url
