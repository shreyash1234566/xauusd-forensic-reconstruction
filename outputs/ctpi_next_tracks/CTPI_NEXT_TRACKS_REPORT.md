# CTPI Next Tracks — Data Requirement and Validated-Component Replay

## Track 1 — Sample-size power under the frozen planted mechanism

| N | Scenario | Clock MDL pass | Direction MDL pass | Joint MDL pass | Median clock net bits |
|---:|---|---:|---:|---:|---:|
| 800 | censored_execution_noise | 32.0% | 100.0% | 32.0% | -8.4 |
| 800 | continuous_low_noise | 21.0% | 100.0% | 21.0% | -10.6 |
| 1600 | censored_execution_noise | 100.0% | 100.0% | 100.0% | 64.9 |
| 1600 | continuous_low_noise | 100.0% | 100.0% | 100.0% | 65.8 |
| 3200 | censored_execution_noise | 100.0% | 100.0% | 100.0% | 214.3 |
| 3200 | continuous_low_noise | 100.0% | 100.0% | 100.0% | 216.4 |

First tested N with at least 80% joint MDL acceptance:

- Continuous low noise: **1600**
- Censored/execution noise: **1600**

These are grid results under the tested mechanism and noise models, not a
universal minimum data requirement.

## Track 2 — Frozen validated-component deterministic projection

The continuous intensity score is converted to signals with one threshold
selected strictly on discovery data. It is then frozen for buffer and lockbox.

| Partition | Entry precision | Entry recall | Entry F1 | Entry+direction precision | Entry+direction recall | Entry+direction F1 |
|---|---:|---:|---:|---:|---:|---:|
| discovery | 0.0202 | 0.0189 | 0.0195 | 0.0101 | 0.0095 | 0.0098 |
| buffer | 0.2000 | 1.0000 | 0.3333 | 0.0000 | 0.0000 | 0.0000 |
| lockbox | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| COMPLETE_LEDGER | 0.0177 | 0.0167 | 0.0172 | 0.0076 | 0.0071 | 0.0074 |

For the complete ledger, the Phase 12 M3 baseline had precision
**0.0935**, recall **0.1190**, and F1
**0.1047**. The validated-component projection has precision
**0.0177**, recall **0.0167**, and F1
**0.0172**.

This does not identify a source trigger. Clock and tick rate define an intensity,
not an entry command; the discovery-frozen threshold is an explicit diagnostic
projection. Exit and sizing remain outside this replay.
