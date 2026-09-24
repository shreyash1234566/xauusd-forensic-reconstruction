# Data needed to move beyond the trade-only fingerprint

The current file supports a behavioral analysis of executed, closed records. It does not expose the market or account state that caused those records. The following inputs are needed in priority order.

## Broker and symbol metadata

- Broker name and server name.
- Server timezone, including daylight-saving rules over the full sample.
- MT4/MT5 Symbol Specification for `XAUUSD.f`: description, digits, tick size, tick value, contract size, calculation mode, margin/profit currency, sessions, swaps and commissions.
- Original HTML/PDF account statement so the eight exported fields can be mapped to the source format.

## Complete order and deal history

- Orders, deals and positions with stable linking identifiers.
- Order comments, magic numbers, EA identifiers and reason codes.
- Requested and executed prices, entry and exit prices, bid/ask, spread, commission and swap.
- Stop-loss and take-profit values and modifications.
- Partial fills/closes, pending orders, modifications, cancellations and rejections.
- Decision/arrival timestamp, submission timestamp and fill timestamp where available.

## Account and risk state

- Balance and equity series.
- Deposits, withdrawals and credits.
- Free margin, used margin and leverage changes.
- All simultaneous positions, including other symbols.

## Market environment

- Broker-specific bid/ask tick data from at least `2025-09-25T19:32:56` through `2026-09-18T06:33:14`, in the server timezone.
- If ticks are unavailable, broker-specific 1-minute OHLC with spread and volume. Coarser bars can supplement but not replace it for short holds.
- Trading-session calendar, outages and symbol-hours changes.
- A versioned economic-event calendar with original release timestamps and revisions for event-driven tests.

## Required file schemas

The optional market-data module accepts a CSV with `timestamp,open,high,low,close` and optional `volume`. The timestamp must be unambiguously documented. A generic feed must be stored separately and marked as exploratory; it must not silently replace the broker feed.

