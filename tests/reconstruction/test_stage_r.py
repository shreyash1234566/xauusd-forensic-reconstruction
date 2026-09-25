import json

import pandas as pd

from reverse_trade.reconstruction.stage_r import _mask, build_minute_trajectory, run_stage_r


def _risk_set(path):
    times = pd.date_range("2026-01-01", periods=240, freq="min", tz="UTC")
    rows = []
    for index, time in enumerate(times):
        base = {
            "decision_time_utc": time + pd.Timedelta(nanoseconds=1),
            "source_quote_time_utc": time,
            "row_role": "control", "feature_status": "observed",
            "hour_utc": time.hour + time.minute / 60, "day_of_week": time.dayofweek,
            "ret_5s": float(index % 7), "ret_30s": float(index % 11),
            "range_30s": float(index % 5), "realized_vol_30s": float(index % 13),
            "spread_now": 0.1 + (index % 3) * 0.01, "tick_rate_30s": 2.0 + index % 4,
        }
        rows.append(base)
        if index % 12 == 0:
            rows.append({**base, "row_role": "case"})
    pd.DataFrame(rows).to_csv(path, index=False)
    return times


def test_minute_trajectory_does_not_duplicate_case_exposure(tmp_path):
    path = tmp_path / "risk.csv"
    times = _risk_set(path)
    panel = build_minute_trajectory(path)
    assert len(panel) == len(times)
    assert panel.case_count.sum() == 20
    assert panel.is_trade_entry.sum() == 20


def test_crossing_and_persistence_reset_across_gap():
    frame = pd.DataFrame({
        "x": [0.0, 2.0, 2.0, 2.0],
        "adjacent_previous_minute": [False, True, False, True],
    })
    pred = {"feature": "x", "operator": ">", "threshold": 1.0}
    assert _mask(frame, {"type": "crossing", "predicate": pred}).tolist() == [False, True, False, False]
    assert _mask(frame, {"type": "persistence", "predicate": pred, "periods": 2}).tolist() == [False, False, False, True]


def test_stage_r_runs_with_inner_selection_and_outer_evaluation(tmp_path):
    risk = tmp_path / "risk.csv"
    times = _risk_set(risk)
    splits = [
        {"fold_id": "f1", "train_end": times[119].isoformat(), "test_start": times[120].isoformat(), "test_end": times[159].isoformat()},
        {"fold_id": "f2", "train_end": times[159].isoformat(), "test_start": times[160].isoformat(), "test_end": times[199].isoformat()},
    ]
    split_path = tmp_path / "splits.json"
    split_path.write_text(json.dumps(splits), encoding="utf-8")
    summary = run_stage_r(risk, split_path, tmp_path / "out")
    assert summary["status"] == "passed_bounded_search_complete"
    assert summary["candidate_selection_used_outer_test"] is False
    assert set(summary["families_searched"]) == {"and", "armed", "crossing", "persistence"}
