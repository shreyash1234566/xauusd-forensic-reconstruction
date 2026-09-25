"""Source-indexed access to genuine raw tick files.

The loader reads only the supplied JSON ticks and records their source files.
It never forward-fills a missing hour or interpolates a quote.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def _hour_key(time: pd.Timestamp) -> str:
    timestamp = pd.Timestamp(time)
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    return timestamp.floor("h").strftime("%Y-%m-%dT%H-00-00-000Z")


def tick_path(ticks_dir: Path, time: pd.Timestamp) -> Path:
    return ticks_dir / f"xauusd_ticks_{_hour_key(time)}.json"


def load_tick_hour(ticks_dir: Path, hour: pd.Timestamp, *, provider_id: str = "canonical_public_ticks") -> pd.DataFrame:
    """Load a single hourly raw file or return an explicitly empty source frame."""

    path = tick_path(ticks_dir, hour)
    columns = ["timestamp_utc", "bid", "ask", "provider_id", "source_file"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not raw:
        return pd.DataFrame(columns=columns)
    first = raw[0]
    if isinstance(first, dict):
        timestamp = [item["timestamp"] for item in raw]
        ask = [item["askPrice"] for item in raw]
        bid = [item["bidPrice"] for item in raw]
    elif isinstance(first, list):
        matrix = np.asarray(raw, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] < 3:
            raise ValueError(f"Invalid list tick schema in {path}")
        timestamp, ask, bid = matrix[:, 0].astype(np.int64), matrix[:, 1], matrix[:, 2]
    else:
        raise ValueError(f"Unsupported tick schema in {path}")
    result = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(timestamp, unit="ms", utc=True),
        "bid": np.asarray(bid, dtype=float), "ask": np.asarray(ask, dtype=float),
        "provider_id": provider_id, "source_file": path.name,
    })
    if (result.bid > result.ask).any() or (result.bid <= 0).any() or (result.ask <= 0).any():
        raise ValueError(f"Invalid bid/ask values in {path}")
    hour_start = pd.Timestamp(hour)
    hour_start = hour_start.tz_localize("UTC") if hour_start.tzinfo is None else hour_start.tz_convert("UTC")
    hour_start = hour_start.floor("h")
    if not result.timestamp_utc.ge(hour_start).all() or not result.timestamp_utc.lt(hour_start + pd.Timedelta(hours=1)).all():
        raise ValueError(f"Tick timestamps fall outside the hour encoded by {path.name}")
    duplicate_rows = result.loc[result.timestamp_utc.duplicated(keep=False)]
    if not duplicate_rows.empty and duplicate_rows.groupby("timestamp_utc")[["bid", "ask"]].nunique().gt(1).any().any():
        raise ValueError(f"Conflicting quotes share timestamps in {path}; source ordering is ambiguous")
    return result.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc", keep="last").reset_index(drop=True)


def load_tick_interval(ticks_dir: Path, start: pd.Timestamp, end: pd.Timestamp, *, provider_id: str = "canonical_public_ticks") -> pd.DataFrame:
    """Read an interval without manufacturing support for missing hours."""

    start_utc = pd.Timestamp(start)
    end_utc = pd.Timestamp(end)
    start_utc = start_utc.tz_localize("UTC") if start_utc.tzinfo is None else start_utc.tz_convert("UTC")
    end_utc = end_utc.tz_localize("UTC") if end_utc.tzinfo is None else end_utc.tz_convert("UTC")
    if end_utc < start_utc:
        raise ValueError("end precedes start")
    frames = [load_tick_hour(ticks_dir, hour, provider_id=provider_id) for hour in pd.date_range(start_utc.floor("h"), end_utc.floor("h"), freq="h", tz="UTC")]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["timestamp_utc", "bid", "ask", "provider_id", "source_file"])
    result = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc", kind="mergesort")
    result = result.drop_duplicates("timestamp_utc", keep="last")
    return result.loc[(result.timestamp_utc >= start_utc) & (result.timestamp_utc <= end_utc)].reset_index(drop=True)
