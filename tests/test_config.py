import os
from unittest.mock import patch

import pytest

from newsfeed.config import load_config


class TestLoadConfig:
    def test_raises_when_required_vars_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="missing required env vars"):
                load_config()

    def test_succeeds_with_all_required_vars(self):
        env = {
            "GOOGLE_CLOUD_PROJECT": "my-project",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            assert cfg.google_cloud_project == "my-project"
