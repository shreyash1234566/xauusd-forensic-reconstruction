# Phase 8E Baseline: Frozen Phase 8D Parameterization & Investigation Scope

**Document Version**: 1.0.0  
**Date**: September 20, 2026  
**Status**: Frozen Baseline from Phase 8D Forensic Reconstruction  
**Canonical Dataset**: 423 Closed Trades on `XAUUSD.f` (Gold CFD), Sept 25, 2025 – Sept 18, 2026  
**Market Data**: 402,151 M1 Bars, 7,144,380 Real Raw Ticks  

---

## 1. Purpose of Phase 8E Baseline

Phase 8D achieved partial structural identification of the system, identifying sub-minute tick momentum dynamics and point-process clustering, while reporting:
- 140,382 raw candidate signals on 402,151 M1 opportunity bars
- 17,174 single-position simulated trades
- 319 / 423 observed trades matched within $\le 5$ minutes ($75.41\%$ historical recall)
- Test split chronological recall of $47.67\%$
- Apparent account-state classification ROC-AUC of $\approx 0.998$

Phase 8E freezes all Phase 8D parameters and artifacts without modification and establishes the audit framework to:
1. Conduct a rigorous, line-by-line computational lineage audit of the $0.998$ account-state AUC to detect potential target/ticket leakage.
2. Separate **Eligibility (Model A)** from **Market Entry Signal (Model B)**.
3. Conduct **Conditional-on-Flat Analysis** to isolate what differentiates real entries from flat non-entry opportunities.
4. Evaluate debounce, event-locking, and first-passage mechanisms to resolve the 140,382 candidate signal explosion.

---

## 2. Frozen Phase 8D Parameters & Claims

The following specific parameter values and operational claims from Phase 8D are strictly frozen for empirical audit:

```
+===============================================================================================+
|                               FROZEN PHASE 8D PARAMETER SPECIFICATION                         |
+--------------------------+-----------------------+--------------------------------------------+
| Component                | Parameter Name        | Frozen Value / Definition                  |
+--------------------------+-----------------------+--------------------------------------------+
| Microstructure Trigger   | Window Horizon        | 5.0 seconds (and 3.0s, 10.0s secondary)    |
| Microstructure Trigger   | Displacement (|ΔP|)   | >= $0.10 price move ($0.05 - $0.20 tested) |
| Microstructure Trigger   | Acceleration (α_10s)  | >= $0.20 tick acceleration                 |
| Microstructure Filter    | Max Spread (Spread_5s)| <= $1.00 floating spread                   |
| Directional Classifier   | Linear Weights        | 0.461*dist_low_60s + 0.305*accel_60s       |
| Supervisory Envelope     | Active Session Window | 05:00 - 16:00 UTC (07:00 - 18:00 EET)      |
| Supervisory Envelope     | Weekend Risk Lockout  | Friday post-20:00 UTC (0 entries observed) |
| Supervisory Envelope     | Overnight Dormancy    | 00:00 - 04:00 UTC (3.07% entries observed) |
| Account State Engine     | Concurrency Rule      | Strict Single-Position (PositionsTotal==0) |
| Account State Engine     | Inter-trade Cooldown  | >= 2 minutes                               |
| Sizing Logic             | Lot Size Rule         | UNRESOLVED (0.01 base, 21x 0.02, 1x 0.03)  |
| Exit Model (Candidate)   | Take Profit (TP)      | +$1.80 ($18.00 / 0.01 lot)                 |
| Exit Model (Candidate)   | Stop Loss (SL)        | -$2.50 ($25.00 / 0.01 lot)                 |
| Exit Model (Candidate)   | Max Duration          | 12 minutes (Fast Scalper mode)             |
+--------------------------+-----------------------+--------------------------------------------+
```

---

## 3. Surviving Forensic Evidence

The following empirical facts remain verified and established across all phases:
1. **Instrument Identity**: 100% `XAUUSD.f` (Gold CFD, fractional spread account).
2. **Trade Volume & Counts**: 423 total closed trades (214 Buy, 209 Sell; 401 at 0.01 lot, 21 at 0.02 lot, 1 at 0.03 lot).
3. **Execution Timestamp Distribution**: Uniform distribution across seconds 0 to 59 of the minute ($\chi^2 = 63.67, p = 0.3157$), ruling out periodic bar-close polling.
4. **Institutional Liquidity Concentration**: $43.50\%$ of trades occur in London Open ($24.35\%$), US Releases/NY Open ($12.77\%$), and London PM Fix ($6.38\%$).
5. **Non-Poisson Arrival Clustering**: Positive burstiness ($B = +0.0591$), Weibull decaying hazard ($k = 0.8331 < 1.0$), and Gamma arrival process outperforming Poisson null ($\Delta\text{AIC} = 25.80, p = 2.49 \times 10^{-6}$).
6. **Single-Position Concurrency**: $420$ of $423$ trades ($99.29\%$) executed with strictly zero open positions.

---

## 4. Falsified Hypotheses (Excluded Models)

1. **Discrete Bar-Close (OnBar) Polling**: Decisively falsified by uniform second-of-minute entry distribution ($p = 0.3157$).
2. **Fixed 07:00–16:00 Rigid Automated Clock**: Falsified by continuous circadian hazard and presence of out-of-window trades.
3. **Rigid Trailing Stop ($+\$3.00$ trigger / $\$1.00$ distance)**: Falsified in Phase 8C ($99.29\%$ parameter mismatch with real MFE/MAE paths).
4. **Aggressive Martingale Loss Recovery**: Falsified by consistent 0.01 lot baseline with only 21 isolated 0.02 lot positions.
5. **Pure M1 Indicator Separation**: Falsified by high observational equivalence ($140,382$ background M1 bars sharing identical technical indicator states).

---

## 5. Unresolved Components for Phase 8E Investigation

1. **Account-State $0.998$ AUC Validation**: Audit whether feature construction in `phase8d_05_information_boundary.csv` contained target/ticket leakage between real trades and synthetic controls.
2. **Separation of Eligibility vs Market Signal**: Isolate Model A (eligibility) from Model B (entry trigger) to prevent confounding.
3. **Conditional-on-Flat False Positive Explosion**: Identify why raw 5-second momentum generates 140k candidate signals and evaluate debounce, first-crossing, and state reset mechanisms.
4. **Exact Pre-Entry Causal Event Sequence**: Pinpoint the millisecond/tick first-passage dynamics and nearest-neighbor differentiators between real trades and identical flat controls.
5. **Position Sizing Dynamics**: Determine if 0.02 lot sizing is causally predictable or represents discretionary manual intervention.
6. **Exit Rule Reconstruction**: Formalize candidate exit models without confounding entry trigger recovery.
7. **Production MQL5 Syntax & Semantics Validation**: Ensure full operational fidelity of reconstructed Expert Advisor code.
