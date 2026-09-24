"""Planning support for label-independent supplemental tick acquisition."""

from __future__ import annotations

from typing import Any

import pandas as pd


def acquisition_plan_from_coverage(coverage: pd.DataFrame, *, provider_id: str) -> pd.DataFrame:
    """Create a missing-hour request manifest; this function performs no network I/O."""

    required = {"intended_hour_utc", "support_status"}
    missing = required.difference(coverage.columns)
    if missing:
        raise ValueError(f"Coverage lacks fields: {sorted(missing)}")
    plan = coverage.loc[coverage["support_status"].ne("observed"), ["intended_hour_utc", "status"]].copy()
    plan["provider_id"] = provider_id
    plan["request_status"] = "planned"
    plan["label_independent"] = True
    return plan.rename(columns={"intended_hour_utc": "requested_hour_utc", "status": "canonical_status"}).reset_index(drop=True)
