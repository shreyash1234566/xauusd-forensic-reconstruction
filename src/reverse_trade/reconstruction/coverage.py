"""Coverage inventory for raw public tick files without inventing observations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .io import sha256


_NAME = re.compile(r"^xauusd_ticks_(\d{4}-\d{2}-\d{2}T\d{2}-00-00-000Z)\.json$")


def parse_hour_filename(path: Path) -> pd.Timestamp:
    match = _NAME.match(path.name)
    if not match:
        raise ValueError(f"Not a canonical hourly tick filename: {path.name}")
    return pd.Timestamp(match.group(1).replace("-00-00-000Z", ":00:00Z"), tz="UTC")


def _decode_ticks(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)
    if not values:
        return np.array([], dtype=np.int64), np.array([], dtype=float), np.array([], dtype=float)
    first = values[0]
    if isinstance(first, dict):
        ts = np.asarray([item["timestamp"] for item in values], dtype=np.int64)
        ask = np.asarray([item["askPrice"] for item in values], dtype=float)
        bid = np.asarray([item["bidPrice"] for item in values], dtype=float)
    elif isinstance(first, list):
        array = np.asarray(values, dtype=float)
        if array.ndim != 2 or array.shape[1] < 3:
            raise ValueError("List tick rows require timestamp, ask, and bid")
        ts, ask, bid = array[:, 0].astype(np.int64), array[:, 1], array[:, 2]
    else:
        raise ValueError("Unsupported tick JSON schema")
    return ts, ask, bid


def inspect_tick_file(path: Path, *, include_hash: bool = False) -> dict[str, Any]:
    intended = parse_hour_filename(path)
    result: dict[str, Any] = {
        "file": path.name,
        "intended_hour_utc": intended,
        "bytes": path.stat().st_size,
        "status": "ok",
    }
    try:
        ts, ask, bid = _decode_ticks(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result.update({"status": "invalid", "error": type(exc).__name__, "tick_count": 0})
        return result
    result["tick_count"] = int(len(ts))
    if len(ts) == 0:
        result["status"] = "empty"
    else:
        time = pd.to_datetime(ts, unit="ms", utc=True)
        diffs = np.diff(ts)
        result.update({
            "first_tick_utc": time[0],
            "last_tick_utc": time[-1],
            "monotonic_non_decreasing": bool(np.all(diffs >= 0)),
            "duplicate_timestamp_count": int(len(ts) - len(np.unique(ts))),
            "negative_or_crossed_quote_count": int(np.count_nonzero((bid <= 0) | (ask <= 0) | (bid > ask))),
            "largest_interquote_gap_seconds": float(diffs.max() / 1000.0) if len(diffs) else 0.0,
        })
        if (
            not result["monotonic_non_decreasing"]
            or result["negative_or_crossed_quote_count"]
            or (time < intended).any()
            or (time >= intended + pd.Timedelta(hours=1)).any()
            or not np.isfinite(ask).all()
            or not np.isfinite(bid).all()
        ):
            result["status"] = "invalid"
    if include_hash:
        result["sha256"] = sha256(path)
    return result


def build_coverage_inventory(
    ticks_dir: Path,
    *,
    include_hash: bool = False,
    expected_start: pd.Timestamp | None = None,
    expected_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Inventory files and, when requested, explicitly include absent hours.

    The expected range is a calendar range, not an assertion that the market
    should have been open every hour. Absent and empty hours remain unknown.
    """
    rows = [inspect_tick_file(path, include_hash=include_hash) for path in sorted(ticks_dir.glob("xauusd_ticks_*.json"))]
    if not rows:
        raise FileNotFoundError(f"No canonical raw tick files found in {ticks_dir}")
    result = pd.DataFrame(rows)
    result["support_status"] = np.where(result["status"].eq("ok") & result["tick_count"].gt(0), "observed", "unknown")
    if expected_start is not None or expected_end is not None:
        if expected_start is None or expected_end is None:
            raise ValueError("expected_start and expected_end must be supplied together")
        start = pd.Timestamp(expected_start)
        end = pd.Timestamp(expected_end)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        if end < start:
            raise ValueError("expected_end precedes expected_start")
        start, end = start.floor("h"), end.floor("h")
        result["in_expected_span"] = result["intended_hour_utc"].between(start, end, inclusive="both")
        expected = pd.DataFrame({"intended_hour_utc": pd.date_range(start, end, freq="h", tz="UTC")})
        present = set(pd.to_datetime(result["intended_hour_utc"], utc=True))
        missing = expected.loc[~expected["intended_hour_utc"].isin(present)].copy()
        if not missing.empty:
            missing["file"] = missing["intended_hour_utc"].map(
                lambda value: f"xauusd_ticks_{value.strftime('%Y-%m-%dT%H-00-00-000Z')}.json"
            )
            missing["bytes"] = 0
            missing["status"] = "missing_file"
            missing["tick_count"] = 0
            missing["support_status"] = "unknown"
            missing["in_expected_span"] = True
            result = pd.concat([result, missing], ignore_index=True, sort=False)
    return result.sort_values("intended_hour_utc", kind="mergesort").reset_index(drop=True)


def supported_at(coverage: pd.DataFrame, time: pd.Timestamp, *, lookback: pd.Timedelta = pd.Timedelta(0)) -> bool:
    """Require valid quotes spanning the lookback with bounded hourly gaps."""

    target = pd.Timestamp(time)
    target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
    start_time = target - lookback
    hours = pd.date_range(start_time.floor("h"), target.floor("h"), freq="h", tz="UTC")
    mask = pd.to_datetime(coverage["intended_hour_utc"], utc=True).isin(hours)
    subset = coverage.loc[mask & coverage["support_status"].eq("observed")].copy()
    needed = {"first_tick_utc", "last_tick_utc", "largest_interquote_gap_seconds"}
    if len(subset) != len(hours) or not needed.issubset(subset.columns):
        return False
    gaps = pd.to_numeric(subset["largest_interquote_gap_seconds"], errors="coerce")
    if gaps.isna().any() or (gaps > 60.0).any():
        return False
    first = pd.to_datetime(subset["first_tick_utc"], utc=True, errors="coerce")
    last = pd.to_datetime(subset["last_tick_utc"], utc=True, errors="coerce")
    if first.isna().any() or last.isna().any():
        return False
    return bool(first.min() <= start_time + pd.Timedelta(seconds=60) and last.max() >= target - pd.Timedelta(seconds=60))
