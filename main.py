import logging
import os
import sys

from newsfeed.logging_config import configure_logging
from newsfeed.runner import run


def main() -> None:
    """newsfeed パイプラインのエントリポイントです。"""
    configure_logging(os.environ["APP_ENV"])
    try:
        run()
    except Exception as e:
        logging.getLogger(__name__).critical("newsfeed job failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
