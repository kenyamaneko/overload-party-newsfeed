"""テスト全体で共有する pytest フィクスチャ。"""
import logging
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import redis
from testcontainers.community.google import PubSubContainer
from testcontainers.redis import RedisContainer

_EMULATOR_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators"
_TOPIC_NAME = "test-article-collected"


@pytest.fixture
def preserve_root_logger():
    """ルートロガーのハンドラとレベルを退避し、テスト終了後に復元する。

    configure_logging はルートロガーのハンドラを丸ごと置き換えるため、
    この fixture を挟まないと設定が他のテストへ漏れる。

    Yields:
        None
    """
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture(scope="session")
def valkey_url():
    """テストセッション全体で共有する Valkey container の接続 URL。

    Yields:
        str: 起動した container への redis:// 接続 URL。
    """
    with RedisContainer("valkey/valkey:8-alpine") as valkey:
        host = valkey.get_container_host_ip()
        port = valkey.get_exposed_port(valkey.port)
        yield f"redis://{host}:{port}"


class FeedServer:
    """RSS ソースの応答をテストごとに登録できるローカル HTTP サーバ。"""

    def __init__(self, base_url: str, routes: dict) -> None:
        self._base_url = base_url
        self._routes = routes

    def serve_feed(
        self,
        path: str,
        body: str,
        status: int = 200,
        content_type: str = "application/rss+xml",
    ) -> str:
        """指定パスが返す本文とヘッダを登録する。

        Args:
            path: 応答を登録するパス。
            body: 応答の本文。
            status: 応答の HTTP ステータス。
            content_type: 応答の Content-Type。

        Returns:
            登録したパスの URL。
        """
        self._routes[path] = (status, {"Content-Type": content_type}, body.encode())
        return self._base_url + path

    def serve_redirect(self, path: str, location: str, status: int = 301) -> str:
        """指定パスをリダイレクト応答として登録する。

        Args:
            path: 応答を登録するパス。
            location: リダイレクト先の URL。
            status: 応答の HTTP ステータス。

        Returns:
            登録したパスの URL。
        """
        self._routes[path] = (status, {"Location": location}, b"")
        return self._base_url + path


@pytest.fixture
def feed_server():
    """テストごとに応答を登録できるローカル HTTP サーバを起動する。

    Yields:
        FeedServer: 応答を登録するための操作口。
    """
    routes: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in routes:
                self.send_error(404)
                return
            status, headers, body = routes[self.path]
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    try:
        yield FeedServer(f"http://{host}:{port}", routes)
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="session")
def pubsub_emulator():
    """テストセッション全体で共有する Pub/Sub emulator container。

    Yields:
        PubSubContainer: 起動済みの emulator container。
    """
    with PubSubContainer(image=_EMULATOR_IMAGE) as emulator:
        yield emulator


@pytest.fixture
def pubsub_topic(pubsub_emulator):
    """テストごとに独立した project 上に topic と subscription を用意する。

    Yields:
        tuple[str, str, str]: (project_id, topic 名, subscription_path)。
    """
    project_id = f"test-{uuid.uuid4().hex}"
    publisher_client = pubsub_emulator.get_publisher_client()
    subscriber_client = pubsub_emulator.get_subscriber_client()
    topic_path = publisher_client.topic_path(project_id, _TOPIC_NAME)
    publisher_client.create_topic(name=topic_path)
    subscription_path = subscriber_client.subscription_path(project_id, "test-sub")
    subscriber_client.create_subscription(name=subscription_path, topic=topic_path)

    yield project_id, _TOPIC_NAME, subscription_path

    subscriber_client.close()


@pytest.fixture
def redis_client(valkey_url):
    """テストごとに FLUSHDB 済みの Valkey クライアントを用意する。

    Yields:
        redis.Redis: FLUSHDB 済みのクライアント。テスト終了時に close する。
    """
    c = redis.from_url(valkey_url, decode_responses=True)
    c.flushdb()
    yield c
    c.close()
