# Reverse-trade forensic research project

This project produces an evidence-graded behavioral fingerprint from a supplied
headerless trade-history TSV. It does not claim to recover source code or a
specific entry/exit strategy from selected closed trades alone.

## Deliverables

- `outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d/reverse_engineering_report.md` — the complete A–T research report.
- `outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d/tables/` — proof log, hypothesis register, statistical tests, candidate ranking and reproducible intermediate tables.
- `outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d/reverse_trade_analysis.xlsx` — spreadsheet handoff with formulas and charts.
- `outputs/market_reconstruction/market_reconstruction_report.md` — clearly labelled exploratory comparison to a non-broker M1 reference feed; it does not identify the strategy.
- `outputs/market_reconstruction/algorithm_identification_status.md` — final continuation verdict and evidence boundary.
- `outputs/market_reconstruction/algorithm_claim_audit.md` — claim-by-claim grading of the imported P1–P9b findings and the completed P10 work.
- `outputs/market_reconstruction/candidate_event_table.csv.gz` — leakage-safe M1 opportunity panel with completed M5/M15/H1 context.
- `outputs/market_reconstruction/entry_match_table.csv` and `exit_match_table.csv` — per-trade historical/OOS replication results.

## Reproduce the trade-history analysis

From the project root, activate the local environment and run:

```powershell
.\.venv\Scripts\python.exe -m reverse_trade.pipeline --input data\raw\trades_raw.tsv --output outputs\01a0bada-7e73-77c0-9b06-15db62fdf55d
.\.venv\Scripts\python.exe -m reverse_trade.report --output outputs\01a0bada-7e73-77c0-9b06-15db62fdf55d --project-root .
.\.venv\Scripts\python.exe -m pytest
```

To rerun the continuation analysis and its independent validation:

```powershell
.\.venv\Scripts\python.exe scripts\continue_identification.py
.\.venv\Scripts\python.exe scripts\validate_continuation.py
```

The copied raw input is retained unchanged in `data/raw/trades_raw.tsv`.
The data requirements needed to test actual entry and exit rules are in
`docs/data_requirements.md`.
