import logging
import sys

from newsfeed.runner import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def main() -> None:
    try:
        run()
    except Exception as e:
        logging.getLogger(__name__).critical("newsfeed job failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
