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
            "DATABASE_URL": "postgresql://localhost/test",
            "GCS_BUCKET": "my-bucket",
            "GCP_PROJECT": "my-project",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            assert cfg.database_url == "postgresql://localhost/test"
            assert cfg.gcs_bucket == "my-bucket"
            assert cfg.gcp_project == "my-project"

    def test_vertex_location_default(self):
        env = {
            "DATABASE_URL": "postgresql://localhost/test",
            "GCS_BUCKET": "my-bucket",
            "GCP_PROJECT": "my-project",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
            assert cfg.vertex_location == "us-central1"
