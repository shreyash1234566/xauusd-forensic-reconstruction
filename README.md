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

## Algorithm Reconstruction Framework (Stages A through Z)

The implementation for evidence-safe hidden-policy reconstruction is
documented in `docs/ALGORITHM_RECONSTRUCTION_IMPLEMENTATION_PLAN_V1.md`.
It preserves the canonical 423-record ledger ($N=423$, SHA-256: `3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD`),
the 420-epoch invariant, the Phase 7C reconciliation, and genuine raw XAUUSD ticks unchanged.

To run the complete reconstruction pipeline:

```powershell
# 1. Audit canonical evidence & 420-epoch invariant
python -m reverse_trade.reconstruction.cli audit --output outputs/reconstruction_v1/audit

# 2. Build coverage inventory over genuine public raw tick stores
python -m reverse_trade.reconstruction.cli coverage --output outputs/reconstruction_v1/coverage

# 3. Generate missing-hour request manifest for gap coverage
python -m reverse_trade.reconstruction.cli plan-acquisition --output outputs/reconstruction_v1/acquisition

# 4. Execute the 12-family planted benchmark recovery suite (Stage N)
python -m reverse_trade.reconstruction.cli benchmark --output outputs/reconstruction_v1/benchmark

# 5. Fit B0-B5 statistical point-process baselines and log-likelihoods (Stage O)
python -m reverse_trade.reconstruction.cli fit-baselines --output outputs/reconstruction_v1/baselines

# 6. Multi-tier AST and state-machine synthesis search (Stages Q, R, S, T)
python -m reverse_trade.reconstruction.cli search --output outputs/reconstruction_v1/search

# 7. Run placebo tests, divergence casebook, and identifiability verdict (Stages U, V, W, X, Y, Z)
python -m reverse_trade.reconstruction.cli evaluate --output outputs/reconstruction_v1/evaluate
```
