# Phase 3 clock-matched near-miss analysis

Each actual trade is matched to a nearby non-trade minute on the same date, raw-clock session and M30 phase, then minimized on pre-entry history and market-state distance. This removes the broad clock match before inspecting state/event differences.

| trade_ticket | clock_event | state_similarity | event_difference | candidate_hidden_condition |
| --- | --- | --- | --- | --- |
| 36094988 | M30 phase 2 | 1.3877 | event_any, event_count | event_any, event_count |
| 36095791 | M30 phase 13 | 1.5144 | same measured event flags | no isolated measured clock/event condition |
| 36148327 | M30 phase 17 | 0.1036 | same measured event flags | no isolated measured clock/event condition |
| 36168589 | M30 phase 16 | 0.26137 | same measured event flags | no isolated measured clock/event condition |
| 36168590 | M30 phase 16 | 0.26137 | same measured event flags | no isolated measured clock/event condition |
| 36227385 | M30 phase 20 | 0.43041 | same measured event flags | no isolated measured clock/event condition |
| 36227388 | M30 phase 20 | 0.43041 | same measured event flags | no isolated measured clock/event condition |
| 36228676 | M30 phase 25 | 1.418 | event_any, event_count | event_any, event_count |
| 36274877 | M30 phase 25 | 0.17551 | event_any, event_count | event_any, event_count |
| 36283671 | M30 phase 28 | 0.6151 | same measured event flags | no isolated measured clock/event condition |
| 36322976 | M30 phase 13 | 0.55252 | same measured event flags | no isolated measured clock/event condition |
| 36334931 | M30 phase 17 | 0.4849 | event_any, event_count | event_any, event_count |
| 36335183 | M30 phase 23 | 1.6485 | same measured event flags | no isolated measured clock/event condition |
| 36335196 | M30 phase 23 | 1.6485 | same measured event flags | no isolated measured clock/event condition |
| 36337657 | M30 phase 13 | 1.0959 | event_count | event_count |

The matched records do not isolate a single repeated hidden condition. They are evidence against the claim that matching M30 clock phase plus broad observable state makes the trade deterministic.
