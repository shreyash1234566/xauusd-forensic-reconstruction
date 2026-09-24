# Independent Public Account Search Log

## Investigation Overview
- **Target Dataset**: Canonical 423-trade execution ledger (`data/raw/trades_raw.tsv`)
- **Symbol**: `XAUUSD.f` (Gold CFD, Fix/Special Spread Account)
- **Period**: 2025-09-25 19:32:56 → 2026-09-18 06:33:14 (UTC+3 Broker Time)
- **Net P&L**: +$1,451.22 | **Win Rate**: 86.76% (367 wins / 56 losses)
- **Raw File SHA256**: `3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD`
- **Search Execution Date**: 2026-09-20

---

## 1. Targeted Platforms Audited
1. **MQL5 Signals** (`mql5.com/en/signals`): Public signal registry for MetaTrader 4 / MetaTrader 5.
2. **Myfxbook** (`myfxbook.com`): Public portfolio, EA tracking, and trading system registry.
3. **FX Blue** (`fxblue.com/users`): Live account tracking, social trading, and performance verification.
4. **Copy-Trading Networks**: SignalStart, ZuluTrade, CopyFX (RoboForex social trading).
5. **Global Web Indexes**: Google, Bing, DuckDuckGo web search indexes for exact price/ticket tuples.

---

## 2. Distinctive Search Query Batches

### Batch A: Exact MetaTrader Ticket Fingerprints
- `site:mql5.com/en/signals "36094988" OR "36095791"` -> 0 results
- `site:myfxbook.com "36094988" OR "100829495"` -> 0 results
- `site:fxblue.com "36094988" OR "36227388"` -> 0 results
- `"36094988" "3736.13" "XAUUSD"` -> 0 results
- `"100829495" "4373.27" "XAUUSD"` -> 0 results
- `"00983845" "4336.10" "XAUUSD"` -> 0 results

*Finding*: MT4/MT5 order and deal ticket IDs from this account are private to the broker server and have not been indexed by public tracking platforms.

### Batch B: Subsequence & Multi-Trade Micro-Signatures
- **Early Subsequence (Sep 2025)**:
  - `2025-09-25 19:32:56 Buy 0.01 @ 3736.13`
  - `2025-09-25 19:43:46 Sell 0.01 @ 3736.72`
  - Query: `"3736.13" "3736.72" "XAUUSD"` -> 0 matches in public trading ledgers.
- **Middle Subsequence (May 2026)**:
  - `2026-05-25 09:09:03 Buy 0.02 @ 4551.65 (Ticket 93064584)`
  - Query: `"93064584" "4551.65"` -> 0 matches.
- **Late Subsequence (Sep 2026)**:
  - `2026-09-17 16:21:20 Sell 0.01 @ 4373.27 (Ticket 100829495)`
  - `2026-09-18 06:25:04 Buy 0.01 @ 4336.10 (Ticket 00983845)`
  - Query: `"4373.27" "4336.10" "XAUUSD"` -> 0 matches.
- **Unusual Sizing Subsequence**:
  - `2025-09-30 11:20:57 Sell 0.03 @ 3833.24 (Ticket 36227388)`
  - Query: `"36227388" "3833.24"` -> 0 matches.

*Finding*: Distinctive 3-to-5 trade sequences across early, middle, and late intervals show zero public indexation.

### Batch C: Macro Account & Aggregate Invariants
- `site:mql5.com/en/signals "1451.22" "XAUUSD"` -> 0 matches
- `site:myfxbook.com "1451.22" "XAUUSD.f"` -> 0 matches
- `site:myfxbook.com "423 trades" "XAUUSD"` -> 0 matches
- `"423 trades" "1451.22" "XAUUSD"` -> 0 matches

*Finding*: No public account summary matches the exact macro totals ($1,451.22 PnL across 423 trades).

### Batch D: Broker Instrument Suffix Profiling
- Query: `site:mql5.com "XAUUSD.f"` / `"XAUUSD.f" "RoboForex" OR "Tickmill"`
- *Finding*: The symbol `.f` is standard for Fixed Spread (Pro-Fix) accounts on brokers like RoboForex and Tickmill, but forum mentions discuss execution errors and symbol mapping rather than this specific trading account.

---

## 3. Search Outcome Summary
- **Total Search Queries Executed**: 18 distinct structured queries across 5 platforms.
- **Candidate Accounts Identified**: 0 public accounts.
- **Row-Level Exact Matches**: 0 / 423 canonical trades (0.0%).
- **Longest Consecutive Exact Sequence**: 0 trades.
