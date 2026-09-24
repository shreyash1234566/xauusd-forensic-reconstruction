# Event-sequence and temporal reconstruction

## Event construction

All event flags are computed on a completed reference M1 bar and are available only at the next minute boundary. They include rolling/session high-low crossings, VWAP and EMA20 crosses, large-body expansion, compression-to-expansion, false breaks, higher-low/lower-high breaks, pullback continuation and immediate reversal. They are descriptive substitutions for possible geometry, not claims that the original code used EMA or VWAP.

## Delay from M1 event boundary to recorded entry

| tolerance | share_of_recorded_entries_after_minute_boundary | median_minutes_since_measured_event |
| --- | --- | --- |
| ≤1s | 0.023641 | 0 |
| ≤2s | 0.042553 | 0 |
| ≤5s | 0.099291 | 0 |
| ≤10s | 0.18913 | 0 |
| ≤15s | 0.26714 | 0 |
| ≤30s | 0.50118 | 0 |
| ≤60s | 1 | 0 |

Entries contain seconds but the proxy is M1. The delay distribution can only test consistency with a completed-minute boundary. It cannot separate first tick after close, a scheduled sub-minute timer, or an intrabar threshold crossing.

## Falsification implication

Even where a completed-bar event is enriched at true entries, the same events occur many times without an order. The event is therefore not a sufficient trigger in the observed M1 proxy.
