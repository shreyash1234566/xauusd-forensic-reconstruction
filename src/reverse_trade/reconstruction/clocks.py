"""Decision-clock generation independent of recorded trade labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import pandas as pd


ClockKind = Literal["tick", "timer", "bar"]


@dataclass(frozen=True)
class ClockSpec:
    kind: ClockKind
    interval: pd.Timedelta | None = None
    phase: pd.Timedelta = pd.Timedelta(0)

    def __post_init__(self) -> None:
        if self.kind == "tick" and self.interval is not None:
            raise ValueError("Tick clock does not have a timer interval")
        if self.kind in {"timer", "bar"} and (self.interval is None or self.interval <= pd.Timedelta(0)):
            raise ValueError(f"{self.kind} clock requires a positive interval")


def _utc(time: pd.Timestamp) -> pd.Timestamp:
    result = pd.Timestamp(time)
    return result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")


def tick_opportunities(quote_times: Iterable[pd.Timestamp]) -> pd.DatetimeIndex:
    """Each received quote is one candidate OnTick boundary, with no labels used."""

    times = pd.DatetimeIndex([_utc(item) for item in quote_times]).unique().sort_values()
    return times


def regular_opportunities(start: pd.Timestamp, end: pd.Timestamp, spec: ClockSpec) -> pd.DatetimeIndex:
    """Generate timer/bar boundaries over an independently declared interval."""

    if spec.kind == "tick" or spec.interval is None:
        raise ValueError("regular_opportunities requires timer or bar clock")
    start_utc, end_utc = _utc(start), _utc(end)
    if end_utc < start_utc:
        raise ValueError("end precedes start")
    epoch = pd.Timestamp("1970-01-01", tz="UTC") + spec.phase
    offset = (start_utc - epoch) % spec.interval
    first = start_utc if offset == pd.Timedelta(0) else start_utc + (spec.interval - offset)
    return pd.date_range(first, end_utc, freq=spec.interval, tz="UTC")


def completed_bar_opportunities(quote_times: Iterable[pd.Timestamp], interval: pd.Timedelta) -> pd.DataFrame:
    """First quote strictly after a bar close; no future-bar feature is implied."""

    if interval <= pd.Timedelta(0):
        raise ValueError("interval must be positive")
    quotes = tick_opportunities(quote_times)
    if quotes.empty:
        return pd.DataFrame(columns=["decision_time_utc", "completed_bar_end_utc"])
    closed = quotes.floor(interval).unique().sort_values()
    rows: list[dict[str, pd.Timestamp]] = []
    for end in closed[1:]:
        matching = quotes[quotes >= end]
        if len(matching):
            rows.append({"decision_time_utc": matching[0], "completed_bar_end_utc": end})
    return pd.DataFrame(rows).drop_duplicates("decision_time_utc").reset_index(drop=True)


@dataclass(frozen=True)
class QuoteClock:
    """Quote/tick clock representing decision points on quote arrivals."""

    def opportunities(self, quote_times: Iterable[pd.Timestamp]) -> pd.DatetimeIndex:
        return tick_opportunities(quote_times)


@dataclass(frozen=True)
class TimerClock:
    """Fixed-interval timer clock."""

    interval: pd.Timedelta = pd.Timedelta(seconds=60)
    phase: pd.Timedelta = pd.Timedelta(0)

    def opportunities(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        spec = ClockSpec("timer", self.interval, self.phase)
        return regular_opportunities(start, end, spec)


@dataclass(frozen=True)
class CompletedBarClock:
    """Completed bar clock emitting decision times at first tick after bar close."""

    interval: pd.Timedelta = pd.Timedelta(minutes=1)

    def opportunities(self, quote_times: Iterable[pd.Timestamp]) -> pd.DataFrame:
        return completed_bar_opportunities(quote_times, self.interval)

