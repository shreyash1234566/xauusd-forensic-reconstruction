"""Validate and hash tick archives without merging provider observations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from reverse_trade.reconstruction.coverage import inspect_tick_file, parse_hour_filename


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--supplemental", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sources = {
        "original_public_archive": root / "data" / "market" / "raw_ticks",
        "dukascopy_supplemental": args.supplemental.resolve(),
    }
    from reverse_trade.reconstruction.evidence import load_canonical_records

    records = load_canonical_records(root)
    start = records.open_time_utc.min().floor("h")
    end = records.close_time_utc.max().floor("h")
    expected = pd.date_range(start, end, freq="h", tz="UTC")
    expected_set = set(expected)
    rows: list[dict[str, object]] = []
    source_summaries: dict[str, dict[str, object]] = {}
    for source_id, directory in sources.items():
        files = sorted(directory.glob("xauusd_ticks_*.json"))
        source_rows: list[dict[str, object]] = []
        for i, path in enumerate(files, start=1):
            inspected = inspect_tick_file(path)
            intended = parse_hour_filename(path)
            row = {
                "source_id": source_id,
                "source_file": path.name,
                "relative_path": path.relative_to(root).as_posix(),
                "intended_hour_utc": intended,
                "in_expected_span": intended in expected_set,
                "sha256": sha256(path),
                **inspected,
            }
            source_rows.append(row)
            if i % 250 == 0 or i == len(files):
                print(f"{source_id}: validated {i}/{len(files)} files", flush=True)
        rows.extend(source_rows)
        frame = pd.DataFrame(source_rows)
        in_span = frame.loc[frame.in_expected_span] if not frame.empty else frame
        observed = in_span.loc[(in_span.status == "ok") & (in_span.tick_count > 0)] if not in_span.empty else in_span
        present_hours = set(pd.to_datetime(in_span.intended_hour_utc, utc=True)) if not in_span.empty else set()
        source_summaries[source_id] = {
            "directory": directory.relative_to(root).as_posix(),
            "files_total": len(frame),
            "files_in_expected_span": len(in_span),
            "missing_expected_hours": len(expected_set - present_hours),
            "nonempty_valid_hours": len(observed),
            "empty_hours": int((in_span.status == "empty").sum()) if not in_span.empty else 0,
            "invalid_hours": int((in_span.status == "invalid").sum()) if not in_span.empty else 0,
            "tick_count": int(observed.tick_count.sum()) if not observed.empty else 0,
            "bytes": int(frame.bytes.sum()) if not frame.empty else 0,
        }
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = pd.DataFrame(rows)
    manifest.to_csv(args.output / "tick_source_manifest.csv", index=False)
    valid_observed_by_source = {}
    for source_id in sources:
        subset = manifest.loc[
            manifest.source_id.eq(source_id)
            & manifest.in_expected_span
            & manifest.status.eq("ok")
            & manifest.tick_count.gt(0)
        ]
        valid_observed_by_source[source_id] = set(pd.to_datetime(subset.intended_hour_utc, utc=True))
    union = set.union(*valid_observed_by_source.values()) if valid_observed_by_source else set()
    report = {
        "expected_calendar_hours": len(expected),
        "span_start_utc": start,
        "span_end_utc": end,
        "sources_are_separate": True,
        "canonical_archive_modified": False,
        "source_summaries": source_summaries,
        "hours_with_nonempty_valid_ticks_in_any_source": len(union),
        "hours_without_nonempty_valid_ticks_in_any_source": len(expected_set - union),
        "warning": "A provider's nonempty hourly file is not proof of full intrahour continuity or of account operation. Empty provider responses are not negative labels.",
    }
    (args.output / "tick_source_validation.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
