# Phase 7C Canonical Source Lock

STATUS = CANONICAL_LOCKED

The canonical trade-to-market alignment artifact is `outputs/market_reconstruction/phase7c_trade_reconciliation.csv`.

This artifact contains the 423 canonical trades reconciled against the genuine historical raw XAUUSD tick stream.

The underlying raw source files are the hourly JSON files in `data/market/raw_ticks/` with names matching `xauusd_ticks_<ISO>.json`.

The canonical 423-row trade ledger remains `data/raw/trades_raw.tsv`.

Do not replace this alignment source with M1 interpolated data, synthetic/modelled feeds, or the earlier bid-only M1 proxy.

- canonical ledger rows: 423
- canonical ledger SHA256: `3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD`
- Phase 7C reconciliation rows: 423
- raw tick hourly JSON files: 2032
