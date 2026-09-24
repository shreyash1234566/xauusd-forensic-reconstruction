"""Chronological folds and validation-isolation checks."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ChronologicalFold:
    fold_id: int
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def make_expanding_folds(event_times: pd.Series, *, minimum_train_events: int = 160, outer_blocks: int = 4) -> list[ChronologicalFold]:
    times = pd.DatetimeIndex(pd.to_datetime(event_times, utc=True).sort_values().unique())
    if len(times) < minimum_train_events + outer_blocks:
        raise ValueError("Insufficient unique event times for requested chronological fold design")
    future = len(times) - minimum_train_events
    block = max(1, future // outer_blocks)
    folds: list[ChronologicalFold] = []
    train_count = minimum_train_events
    for fold_id in range(1, outer_blocks + 1):
        test_start_index = train_count
        if test_start_index >= len(times):
            break
        test_end_index = min(len(times) - 1, test_start_index + block - 1) if fold_id < outer_blocks else len(times) - 1
        folds.append(ChronologicalFold(fold_id, times[train_count - 1], times[test_start_index], times[test_end_index]))
        train_count = test_end_index + 1
    return folds


def assign_fold(frame: pd.DataFrame, time_column: str, fold: ChronologicalFold) -> pd.Series:
    times = pd.to_datetime(frame[time_column], utc=True)
    result = pd.Series("excluded", index=frame.index, dtype="string")
    result.loc[times <= fold.train_end] = "train"
    result.loc[(times >= fold.test_start) & (times <= fold.test_end)] = "test"
    return result


def assert_causal_feature_frame(frame: pd.DataFrame, *, decision_column: str = "decision_time_utc", maximum_input_column: str = "maximum_input_time") -> None:
    if maximum_input_column not in frame:
        return
    decision = pd.to_datetime(frame[decision_column], utc=True)
    maximum = pd.to_datetime(frame[maximum_input_column], utc=True, errors="coerce")
    invalid = maximum.notna() & (maximum >= decision)
    if invalid.any():
        raise ValueError(f"{int(invalid.sum())} feature rows use input at or after their decision boundary")
