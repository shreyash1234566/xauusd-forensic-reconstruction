# Phase 3 data inventory

## Result

The repository was searched outside `outputs/` for CSV, TSV, JSON, Parquet, pickle, SQLite/database, log, archive, MetaTrader-history and spreadsheet files. No tick file, ask series, live spread series, raw broker export, MT4/MT5 order/deal/position history, SL/TP modification record, account history, execution report or platform log was found.

| source | date range | granularity | bid/ask | timezone | symbol | data quality | usable for Phase 3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| data/raw/trades_raw.tsv | 2025-09-25 to 2026-09-18 | closed trade records | neither | as supplied | XAUUSD.f | 423 preserved rows | trade timing/state only |
| data/market/raw/xauusd_m1_utc_raw.csv | 2025-08-01 03:00:00 to 2026-09-18 23:59:00 | M1 OHLCV | bid only | UTC | XAUUSD | 402,401 rows; 296 gaps >5m | completed-bar / clock proxy |
| data/market/normalized/xauusd_m1.csv | 2025-08-01 03:00:00 to 2026-09-18 23:59:00 | M1 OHLCV | bid only | UTC+3 proxy mapping | XAUUSD | 402,401 rows; OHLC integrity checks pass | aligned M1 proxy |
| data/market/test_download/*.csv | 2025-09-25 to 2025-09-26 | M1 sample | bid only | UTC/raw sample | XAUUSD | download/format smoke-test sample | not additional granularity |

## Phase 3 consequence

Tick crossing, bid/ask spread gate, first tick after close, second-level timer, intrabar path, order-book state and actual execution sequence are **UNIDENTIFIABLE** from the available data. The proxy analysis below uses only M1 timestamps and completed M1 bid OHLCV; it cannot convert a clock association into source-code recovery.
