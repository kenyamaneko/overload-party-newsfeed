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


class Test必須環境変数の検証:
    @pytest.mark.parametrize(
        ("env", "missing"),
        [
            pytest.param(
                {"APP_ENV": "local", "VERTEX_LOCATION": "us-central1"},
                "GOOGLE_CLOUD_PROJECT",
                id="GOOGLE_CLOUD_PROJECT が無いとき、ValueError になる",
            ),
            pytest.param(
                {"APP_ENV": "local", "GOOGLE_CLOUD_PROJECT": "p"},
                "VERTEX_LOCATION",
                id="VERTEX_LOCATION が無いとき、ValueError になる",
            ),
            pytest.param(
                _base_env(),
                "APP_ENV",
                id="APP_ENV が無いとき、ValueError になる",
            ),
        ],
    )
    def test_必須環境変数が欠けるとValueErrorになる(self, env, missing):
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match=missing):
                load_config()


class TestAPP_ENVの値の検証:
    def test_localは受理されenv_varのRedis_URLをそのまま採用する(self):
        env = _base_env(APP_ENV="local", UPSTASH_REDIS_URL="redis://localhost:6379/0")
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.redis_url == "redis://localhost:6379/0"

    @patch("newsfeed.config.SecretAccessor")
    def test_productionは受理されSecret_Manager経由のTLS_URLを採用する(self, accessor_cls):
        accessor = MagicMock()
        accessor.access.side_effect = lambda sid: {
            "newsfeed-upstash-redis-endpoint": "upstash.example.com:6379",
            "newsfeed-upstash-redis-password": "s3cr3t",
        }[sid]
        accessor_cls.return_value = accessor

        env = _base_env(APP_ENV="production")
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg.redis_url.startswith("rediss://")

    @pytest.mark.parametrize(
        "invalid",
        [
            pytest.param("dev", id="dev のとき、ValueError で弾く"),
            pytest.param("stg", id="stg のとき、ValueError で弾く"),
            pytest.param("prod", id="prod のとき、ValueError で弾く"),
            pytest.param("staging", id="staging のとき、ValueError で弾く"),
            pytest.param("test", id="test のとき、ValueError で弾く"),
            pytest.param("", id="空文字のとき、ValueError で弾く"),
        ],
    )
    def test_localとproduction以外のAPP_ENVを弾く(self, invalid):
        env = _base_env(APP_ENV=invalid)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="APP_ENV"):
                load_config()


class Testローカルモードの設定読み込み:
    def test_UPSTASH_REDIS_URLとプロジェクト設定をenvから読む(self):
        env = _base_env(
            APP_ENV="local",
            UPSTASH_REDIS_URL="redis://localhost:6379/0",
        )
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            assert cfg.redis_url == "redis://localhost:6379/0"
            assert cfg.google_cloud_project == "my-project"
            assert cfg.vertex_location == "us-central1"

    def test_localでUPSTASH_REDIS_URLが無いとValueErrorになる(self):
        env = _base_env(APP_ENV="local")
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="UPSTASH_REDIS_URL"):
                load_config()


class Testproductionモードの設定読み込み:
    @patch("newsfeed.config.SecretAccessor")
    def test_Secret_Managerから取得した認証情報でrediss_URLを組み立てる(self, accessor_cls):
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
    def test_パスワードのURL予約文字をパーセントエンコードする(self, accessor_cls):
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
