import json

import pandas as pd

from reverse_trade.reconstruction.coverage import build_coverage_inventory
from reverse_trade.reconstruction.ticks import load_tick_hour, load_tick_interval


def _write(path, values) -> None:
    path.write_text(json.dumps(values), encoding="utf-8")


def test_tick_loader_keeps_file_provenance_and_does_not_fill_missing_hour(tmp_path) -> None:
    _write(tmp_path / "xauusd_ticks_2026-01-01T00-00-00-000Z.json", [
        [1767225600000, 101.0, 100.0], [1767225601000, 102.0, 101.0]
    ])
    hour = load_tick_hour(tmp_path, pd.Timestamp("2026-01-01T00:20:00Z"))
    assert hour["source_file"].nunique() == 1
    assert hour["bid"].tolist() == [100.0, 101.0]
    interval = load_tick_interval(tmp_path, pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T01:10:00Z"))
    assert len(interval) == 2
    assert interval["timestamp_utc"].max() < pd.Timestamp("2026-01-01T01:00:00Z")


def test_coverage_inventory_includes_absent_expected_hours_and_marks_extra_files(tmp_path) -> None:
    _write(tmp_path / "xauusd_ticks_2026-01-01T00-00-00-000Z.json", [[1767225600000, 101.0, 100.0]])
    _write(tmp_path / "xauusd_ticks_2025-12-31T23-00-00-000Z.json", [[1767222000000, 101.0, 100.0]])
    inventory = build_coverage_inventory(
        tmp_path,
        expected_start=pd.Timestamp("2026-01-01T00:15:00Z"),
        expected_end=pd.Timestamp("2026-01-01T01:15:00Z"),
    )
    expected = inventory.loc[inventory.in_expected_span]
    assert len(expected) == 2
    assert expected.support_status.tolist() == ["observed", "unknown"]
    assert (~inventory.in_expected_span).sum() == 1
