import os
from dataclasses import dataclass

_REQUIRED_VARS = ("DATABASE_URL", "GCS_BUCKET", "GCP_PROJECT")


@dataclass(frozen=True)
class Config:
    database_url: str
    gcs_bucket: str
    gcp_project: str
    vertex_location: str


def load_config() -> Config:
    missing = [k for k in _REQUIRED_VARS if not os.environ.get(k)]
    if missing:
        raise ValueError(f"missing required env vars: {missing}")
    return Config(
        database_url=os.environ["DATABASE_URL"],
        gcs_bucket=os.environ["GCS_BUCKET"],
        gcp_project=os.environ["GCP_PROJECT"],
        vertex_location=os.environ.get("VERTEX_LOCATION", "us-central1"),
    )
