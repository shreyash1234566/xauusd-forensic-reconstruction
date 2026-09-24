# Methodology and evidence rules

## Observation unit

One TSV row is treated as one closed interval with a ticket-like identifier, direction, apparent open and close timestamps, symbol, size-like value, price-like value and result-like value. Those semantic names are working labels, not verified broker definitions.

## Registered trade-only analyses

- Exact data-integrity and field-domain checks.
- Chronologically sorted directional transition, runs, entropy, autocorrelation and Markov-order tests.
- P&L, holding-time, sizing, raw-clock and trade-gap summaries.
- Permutation tests, whole-day cluster bootstrap intervals and Benjamini-Hochberg correction.
- GMM and Gaussian HMM comparisons using raw-clock circular features, log duration, size-normalized P&L and log entry gap. Direction and lot are held out of the latent-model inputs and used only to profile inferred components.
- PELT sensitivity plus block-permutation one-change scans.
- Expanding-month behavioral stability checks.
- Isolation Forest anomaly ranking. An anomaly is never labeled manual without external evidence.

## Interpretation limits

- Raw-clock counts estimate `P(time | observed trade)`, not `P(trade | time)`.
- Positive rows estimate `P(positive result | exported closed row)`, not an unbiased strategy win probability if rows were filtered.
- Cumulative closed-trade P&L is not account equity and does not include unknown deposits, open-position marks, costs or other symbols.
- A statistical cluster or hidden state is not proof of a separate EA, a market regime or human intervention.
- A distributional change point is not proof that source code changed.
- Market indicators, MFE/MAE, exit type, feed mismatch, event attribution, signal replay and entry/exit parameter recovery remain unavailable until the inputs in `data_requirements.md` are supplied.

## Evidence grades

- **Strong:** exact file fact or result robust to the registered test, multiple-testing control and stated assumptions.
- **Moderate:** consistent across several views or periods but lacks decisive identification data.
- **Weak:** exploratory trade-only association or model-dependent pattern.
- **Unsupported:** not testable from the current file or fails the registered evidence checks.

