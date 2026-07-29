from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import NotFound

from newsfeed.secret_manager import SecretAccessor


class TestSecretの取得:
    @patch("newsfeed.secret_manager.secretmanager.SecretManagerServiceClient")
    def test_secretを取得すると値がutf8の文字列で返る(self, client_cls):
        client = MagicMock()
        response = MagicMock()
        response.payload.data = "ぱすわーど".encode()
        client.access_secret_version.return_value = response
        client_cls.return_value = client

        result = SecretAccessor("my-project").access("my-secret")

        assert result == "ぱすわーど"

    @patch("newsfeed.secret_manager.secretmanager.SecretManagerServiceClient")
    def test_secretを取得すると最新版のパスで問い合わせる(self, client_cls):
        client = MagicMock()
        response = MagicMock()
        response.payload.data = b"value"
        client.access_secret_version.return_value = response
        client_cls.return_value = client

        SecretAccessor("my-project").access("my-secret")

        client.access_secret_version.assert_called_once_with(
            request={"name": "projects/my-project/secrets/my-secret/versions/latest"}
        )

    @patch("newsfeed.secret_manager.secretmanager.SecretManagerServiceClient")
    def test_secretが存在しないときNotFoundが伝播する(self, client_cls):
        client = MagicMock()
        client.access_secret_version.side_effect = NotFound("secret not found")
        client_cls.return_value = client

        with pytest.raises(NotFound):
            SecretAccessor("my-project").access("my-secret")
