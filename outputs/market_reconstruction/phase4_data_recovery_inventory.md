# Phase 4 data-recovery inventory

## Scope and method

A targeted local audit was performed. It checked the project workspace, standard MetaQuotes/MetaTrader/MQL locations, platform installation paths, and trade-relevant user Documents/Downloads locations. It used platform-specific directory names and transaction/tick-oriented filenames and extensions; it did not indiscriminately crawl unrelated operating-system content.

## Expected platform trees

| path | result |
| --- | --- |
| C:\Users\ayush\AppData\Roaming\MetaQuotes | ABSENT |
| C:\Users\ayush\AppData\Local\MetaQuotes | ABSENT |
| C:\Users\ayush\AppData\Local\VirtualStore\MetaQuotes | ABSENT |
| C:\Program Files\MetaTrader 4 | ABSENT |
| C:\Program Files\MetaTrader 5 | ABSENT |
| C:\Program Files (x86)\MetaTrader 4 | ABSENT |
| C:\Program Files (x86)\MetaTrader 5 | ABSENT |

## Audited roots

- E:\reverse -traid (present)
- C:\Users\ayush\AppData\Roaming (present)
- C:\Users\ayush\AppData\Local (present)
- C:\Users\ayush\AppData\Local\VirtualStore (present)
- C:\Program Files (present)
- C:\Program Files (x86) (present)
- C:\Users\ayush\Documents (present)
- C:\Users\ayush\OneDrive\Documents (present)
- C:\Users\ayush\Downloads (present)
- C:\Users\ayush\OneDrive\Downloads (present)

## Relevant candidate inventory

| path | file_type | size_bytes | modified_utc | likely_relevance | tick_bid_ask_order_deal_position_potential | broker_account_symbol_match | coverage_2025_09_25_to_2026_09_18 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E:\reverse -traid\data\raw\trades_raw.tsv | .tsv | 33994 | 2026-09-19T17:31:54.984690+00:00 | Primary supplied closed-trade history. | ticket, side, open/close time, symbol, lot, one observed price, P&L; no order/deal lifecycle or Bid/Ask. | Symbol matches XAUUSD.f; broker/account absent. | Yes: observed entries 2025-09-25T19:32:56 through 2026-09-18T06:25:04. |
| E:\reverse -traid\data\processed\trades_enriched.csv | .csv | 100981 | 2026-09-19T19:45:41.425200+00:00 | Derived from the supplied ledger; not an independent execution source. | No additional quote, order, deal, or position records. | Derived XAUUSD.f ledger; broker/account absent. | Yes, derived from supplied ledger. |
| E:\reverse -traid\data\market\raw\xauusd_m1_utc_raw.csv | .csv | 25098542 | 2026-09-19T20:16:31.566837+00:00 | Dukascopy bid-only M1 proxy used by earlier phases. | ohlc_bar_only; columns are timestamp, open, high, low, close, volume. No Ask, spread, tick sequence, order/deal/position fields. | XAUUSD, not broker-specific XAUUSD.f; no account/server identity. | Yes: 2025-08-01 03:00:00 through 2026-09-18 23:59:00. |
| E:\reverse -traid\data\market\normalized\xauusd_m1.csv | .csv | 26242333 | 2026-09-19T20:17:46.867459+00:00 | Timezone-normalized derivative of the same external M1 proxy. | OHLCV only; cannot become a tick or Bid/Ask feed through normalization. | XAUUSD proxy, not broker/account matched. | Yes: 2025-08-01 03:00:00 through 2026-09-18 23:59:00. |
| E:\reverse -traid\data\market\metadata.json | .json | 1076 | 2026-09-19T20:17:46.869459+00:00 | Documents origin and limitations of the market proxy. | No raw execution fields; declares Dukascopy historical bid M1 source. | No broker/account match. | Metadata describes market coverage above. |
| C:\Users\ayush\OneDrive\Documents\Downloads\crypto_trade.zip | .zip | 43231 | 2026-05-13T15:51:21.876625+00:00 | Trade-named candidate inspected without extraction. | No export data files inside; source code only. No ticks, Bid/Ask, orders, deals, positions, or logs. | Unrelated crypto project; no XAUUSD.f broker/account evidence. | No trading records; not applicable. |

## Finding

No usable platform tree, terminal log, tick database, Bid/Ask/spread export, or order/deal/position lifecycle record was recovered. The two trade-named ZIP archives were inspected as archives and contain unrelated crypto source code, not data exports.
