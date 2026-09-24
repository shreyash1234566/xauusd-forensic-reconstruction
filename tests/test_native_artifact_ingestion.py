from pathlib import Path

from scripts.native_artifact_ingestion import classify_role, inspect_artifact, parse_rows_losslessly


def test_tick_schema_requires_bid_ask_and_time() -> None:
    assert classify_role(["timestamp", "bid", "ask", "volume"]) == "TICK_QUOTE_CANDIDATE"
    assert classify_role(["timestamp", "price", "volume"]) == "UNKNOWN_SCHEMA"


def test_inspection_fingerprints_without_mutating_source(tmp_path: Path) -> None:
    source = tmp_path / "ticks.csv"
    original = "timestamp,bid,ask\n2026-01-01 00:00:00,1,2\n"
    source.write_text(original, encoding="utf-8")
    inspection = inspect_artifact(source)
    assert inspection.role == "TICK_QUOTE_CANDIDATE"
    assert parse_rows_losslessly(source, inspection) == [{"_source_row": 1, "timestamp": "2026-01-01 00:00:00", "bid": "1", "ask": "2"}]
    assert source.read_text(encoding="utf-8") == original
