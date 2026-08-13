"""Configuration for the starter slice.

Everything is an environment variable with a working default, so `python3 run.py
ingest --local` runs with no setup at all. The two AWS names have NO default on
purpose: a slice that silently invents a bucket name is a slice that writes
somewhere you did not intend.
"""

import os
from dataclasses import dataclass

# The Royal Observatory, Greenwich (0 degrees longitude). A deliberately generic
# default: the point of the slice is the pipeline, not where you live. Override
# with SLICE_LAT / SLICE_LON.
DEFAULT_LAT = 51.4779
DEFAULT_LON = -0.0015

# Open-Meteo's ARCHIVE product settles a few days behind real time. Asking for
# yesterday returns nulls, which looks like a broken pipeline and is not one.
ARCHIVE_LAG_DAYS = 6

SOURCE_NAME = "weather"


@dataclass(frozen=True)
class Config:
    user_id: str
    lat: float
    lon: float
    bucket: str | None
    table: str | None
    local_root: str

    @property
    def partition_key(self) -> str:
        """The single-table partition this source writes into."""
        return f"USER#{self.user_id}#SOURCE#{SOURCE_NAME}"

    def raw_key(self, date_str: str) -> str:
        """S3 object key for one day of raw, unmodified API response."""
        year, month, _ = date_str.split("-")
        return f"raw/{self.user_id}/{SOURCE_NAME}/{year}/{month}/{date_str}.json"

    @staticmethod
    def sort_key(date_str: str) -> str:
        return f"DATE#{date_str}"


def load(**overrides) -> Config:
    """Build a Config from the environment, with keyword overrides for tests."""
    cfg = Config(
        user_id=os.environ.get("SLICE_USER_ID", "demo"),
        lat=float(os.environ.get("SLICE_LAT", DEFAULT_LAT)),
        lon=float(os.environ.get("SLICE_LON", DEFAULT_LON)),
        bucket=os.environ.get("SLICE_BUCKET") or None,
        table=os.environ.get("SLICE_TABLE") or None,
        local_root=os.environ.get("SLICE_LOCAL_ROOT", ".slice-data"),
    )
    if overrides:
        cfg = Config(**{**cfg.__dict__, **overrides})
    return cfg
