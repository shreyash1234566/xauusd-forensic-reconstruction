"""Declared, bounded observation scenarios for replay and matching."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class ObservationScenario:
    name: str
    timestamp_tolerance: pd.Timedelta = pd.Timedelta(seconds=1)
    market_order_delay: pd.Timedelta = pd.Timedelta(0)
    ledger_complete_entries: bool = True
    feed_id: str = "canonical_public_ticks"
    description: str = "Declared public-feed observation convention"

    def __post_init__(self) -> None:
        if self.timestamp_tolerance < pd.Timedelta(0) or self.market_order_delay < pd.Timedelta(0):
            raise ValueError("Observation tolerances and delays cannot be negative")

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["timestamp_tolerance_seconds"] = self.timestamp_tolerance.total_seconds()
        data["market_order_delay_seconds"] = self.market_order_delay.total_seconds()
        data.pop("timestamp_tolerance")
        data.pop("market_order_delay")
        return data


DEFAULT_SCENARIOS = (
    ObservationScenario("canonical_instant", description="Canonical public quotes, instantaneous market-fill approximation"),
    ObservationScenario("canonical_1s_tolerance", timestamp_tolerance=pd.Timedelta(seconds=1), description="Canonical public quotes with one-second timestamp uncertainty"),
)
