import os
from unittest.mock import MagicMock, patch
from urllib.parse import unquote, urlparse

import pytest

from newsfeed.config import load_config

_REQUIRED_ENV = {
    "GOOGLE_CLOUD_PROJECT": "test-project",
    "VERTEX_LOCATION": "us-central1",
    "NEWS_ARTICLE_COLLECTED_TOPIC": "test-topic",
}


def _secret_accessor_returning(endpoint: str, password: str) -> MagicMock:
    """指定したエンドポイントとパスワードを返す SecretAccessor の代用を組み立てる。

    Args:
        endpoint: newsfeed-upstash-redis-endpoint 相当の secret として返す値。
        password: newsfeed-upstash-redis-password 相当の secret として返す値。

    Returns:
        newsfeed.config.SecretAccessor と差し替えるための MagicMock クラス。
    """
    accessor = MagicMock()

    def fake_access(secret_id: str) -> str:
        if "endpoint" in secret_id:
            return endpoint
        if "password" in secret_id:
            return password
        raise AssertionError(f"unexpected secret_id: {secret_id}")

    accessor.access.side_effect = fake_access
    return MagicMock(return_value=accessor)


class Test必須環境変数の検証:
    @pytest.mark.parametrize(
        "env, missing_var",
        [
            pytest.param({}, "GOOGLE_CLOUD_PROJECT", id="GOOGLE_CLOUD_PROJECTが未設定のとき"),
            pytest.param(
                {"GOOGLE_CLOUD_PROJECT": "test-project"},
                "VERTEX_LOCATION",
                id="GOOGLE_CLOUD_PROJECTのみ設定されVERTEX_LOCATIONが未設定のとき",
            ),
            pytest.param(
                {"GOOGLE_CLOUD_PROJECT": "test-project", "VERTEX_LOCATION": "us-central1"},
                "NEWS_ARTICLE_COLLECTED_TOPIC",
                id="GOOGLE_CLOUD_PROJECTとVERTEX_LOCATIONのみ設定されNEWS_ARTICLE_COLLECTED_TOPICが未設定のとき",
            ),
            pytest.param(
                {**_REQUIRED_ENV, "APP_ENV": "local"},
                "UPSTASH_REDIS_URL",
                id="APP_ENVがlocalでUPSTASH_REDIS_URLが未設定のとき",
            ),
        ],
    )
    def test_設定の読み込みは未設定の環境変数名を理由とするエラーで失敗する(self, env, missing_var):
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError, match=missing_var):
            load_config()


class TestAPP_ENVの値の検証:
    def test_localともproductionとも異なる値devのときAPP_ENVを理由とするエラーになる(self):
        env = {**_REQUIRED_ENV, "APP_ENV": "dev"}
        with patch.dict(os.environ, env, clear=True), pytest.raises(ValueError, match="APP_ENV"):
            load_config()


class Testlocal環境での設定読み込み:
    def test_読み込んだ設定の各項目が対応する環境変数の値と一致する(self):
        env = {
            **_REQUIRED_ENV,
            "APP_ENV": "local",
            "UPSTASH_REDIS_URL": "redis://localhost:6379/0",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()

        assert cfg.google_cloud_project == "test-project"
        assert cfg.vertex_location == "us-central1"
        assert cfg.news_article_collected_topic == "test-topic"
        assert cfg.redis_url == "redis://localhost:6379/0"


class Testproduction環境での設定読み込み:
    def test_SecretManagerから取得した接続情報でTLS接続用のURLになる(self):
        env = {**_REQUIRED_ENV, "APP_ENV": "production"}
        accessor_cls = _secret_accessor_returning(
            endpoint="fake-endpoint.upstash.io:6379", password="simplepassword",
        )
        with patch.dict(os.environ, env, clear=True), \
                patch("newsfeed.config.SecretAccessor", accessor_cls):
            cfg = load_config()

        parsed = urlparse(cfg.redis_url)
        assert parsed.scheme == "rediss"
        assert parsed.username == "default"
        assert unquote(parsed.password) == "simplepassword"
        assert parsed.hostname == "fake-endpoint.upstash.io"
        assert parsed.port == 6379

    def test_パスワードに区切り文字が含まれるとき区切り文字として解釈されない位置にエンコードされて収まる(self):
        env = {**_REQUIRED_ENV, "APP_ENV": "production"}
        raw_password = "p@ss/w:ord"
        accessor_cls = _secret_accessor_returning(
            endpoint="fake-endpoint.upstash.io:6379", password=raw_password,
        )
        with patch.dict(os.environ, env, clear=True), \
                patch("newsfeed.config.SecretAccessor", accessor_cls):
            cfg = load_config()

        parsed = urlparse(cfg.redis_url)
        assert parsed.scheme == "rediss"
        assert parsed.username == "default"
        assert parsed.hostname == "fake-endpoint.upstash.io"
        assert parsed.port == 6379
        assert unquote(parsed.password) == raw_password
        assert parsed.password != raw_password
