"""Opportunity construction from independently generated clocks and coverage."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from .coverage import supported_at


def build_opportunities(
    decision_times: Iterable[pd.Timestamp], coverage: pd.DataFrame, *, lookback: pd.Timedelta = pd.Timedelta(0)
) -> pd.DataFrame:
    """Mark each candidate clock boundary observed or unknown without labels."""

    rows: list[dict[str, object]] = []
    for time in pd.DatetimeIndex(pd.to_datetime(list(decision_times), utc=True)).unique().sort_values():
        rows.append({
            "decision_time_utc": time,
            "lookback_seconds": lookback.total_seconds(),
            "support_status": "observed" if supported_at(coverage, time, lookback=lookback) else "unknown",
        })
    return pd.DataFrame(rows)


def label_observed_epochs(opportunities: pd.DataFrame, epochs: pd.DataFrame) -> pd.DataFrame:
    """Attach observed labels only after opportunities have been constructed.

    Exact timestamp equality is intentional. Timestamp-tolerance alignment is an
    observation-model task and must not be hidden in risk-set construction.
    """

    result = opportunities.copy()
    result["is_observed_epoch"] = False
    epoch_times = pd.to_datetime(epochs["decision_time_utc"], utc=True)
    mapping = {time: int(epoch_id) for time, epoch_id in zip(epoch_times, epochs["epoch_id"])}
    result["epoch_id"] = pd.to_datetime(result["decision_time_utc"], utc=True).map(mapping)
    result["is_observed_epoch"] = result["epoch_id"].notna()
    return result
