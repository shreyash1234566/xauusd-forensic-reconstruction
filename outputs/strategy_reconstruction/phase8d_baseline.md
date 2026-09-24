# Phase 8D Baseline: Summary of Empirical Findings and Identifiability Boundaries

**Document Version**: 1.0.0  
**Date**: September 20, 2026  
**Status**: Frozen Baseline from Phase 8C Adversarial Falsification  
**Instrument**: XAUUSD.f (Gold Spot CFD)  
**Universe**: 423 Observed Trades, 402,151 M1 Market Bars, 7,100,000+ Raw Market Ticks  

---

## 1. Executive Summary & Purpose

Phase 8C executed an adversarial reconstruction and identifiability audit of the candidate mechanical strategy hypothesis ($H$) developed in Phase 8B. The candidate model proposed a deterministic parameterization consisting of:
- Fixed-window session filter: 07:00–16:00 EET
- Volatility filter: H1 ATR(14) $\ge 0.25\%$
- Micro momentum impulse: M1 $|\Delta P| \ge \$0.30$
- Execution gating: Strict single-position concurrency
- Risk management: Fixed $\$2.50$ Stop Loss with dynamic trailing stop ($+\$3.00$ trigger, $\$1.00$ distance)
- Time decay: 45-minute hard maximum holding duration
- Position sizing: Anti-Martingale 0.01 / 0.02 lot switching

Phase 8D freezes these results as the baseline for deep investigation into hidden triggers, latent states, and execution provenance.

---

## 2. Surviving Empirical Findings (Confirmed Evidence)

The following structural facts have survived rigorous statistical falsification across multiple independent market representations (M1 bars, tick aggregations, and raw tick streams):

1. **Market Instrument & Quotation**:
   - Trading activity is strictly concentrated in `XAUUSD.f` with consistent decimal precision and bid/ask spread dynamics.
2. **Session & Time-of-Day Concentration**:
   - Trades exhibit heavy intraday clustering within European and early US market hours (peak density between 07:00 and 16:00 EET / 05:00 and 14:00 UTC).
   - However, trader presence is governed by a smooth, continuous circadian hazard function ($\text{AIC} = 6292.5$) rather than a rigid automated clock switch ($\text{AIC} = 6365.2$, $p = 1.24 \times 10^{-71}$).
3. **Elevated Volatility Association**:
   - Real trades occur during periods of elevated baseline volatility (mean H1 ATR $= 0.383\%$ vs. $0.294\%$ in non-trade periods).
4. **Sub-Minute Microstructural Momentum**:
   - Directional predictability is absent at the M1 candle level ($50.00\%$ accuracy, $p = 1.000$), but is statistically significant at the 30-second raw tick horizon ($55.85\%$ accuracy, $p = 0.0189$).
5. **Strict Single-Position Execution Policy**:
   - $420$ of $423$ trades ($99.29\%$) exhibit strict single-position concurrency, with exactly $3$ overlapping trade pairs audited as manual/discretionary double-ticket orders.

---

## 3. Falsified Hypotheses (Excluded Models)

The following candidate rules have been decisively rejected by empirical tests and must NOT be reused or re-optimized:

1. **Discrete 07:00–16:00 EET Clock Filter**:
   - Falsified as a rigid automated filter. Fails to account for $24.11\%$ of observed trades executed outside the window, while generating massive negative-space false positives within it.
2. **Fixed $0.30 M1 Impulse Trigger**:
   - Falsified as a standalone or sufficient entry trigger. Produces $123,974$ candidate signals across $402,151$ M1 bars, yielding a catastrophic precision of only $0.221\%$ ($1$ real trade per $452$ signals).
3. **Mechanical Trailing Stop (+ $3.00 / $1.00)**:
   - Falsified via the Critical Exit Test on raw tick trajectories. Mechanical trailing stops trigger prematurely in $82.03\%$ of observed trades, producing an uncorrelated P&L profile ($r = -0.0138$).
4. **45-Minute Hard Maximum Holding Time**:
   - Falsified by continuous hazard rate deconvolution. The empirical exit hazard curve $h(t)$ decays smoothly without any statistical discontinuity or cliff at 45 minutes ($h_{40-45} = 0.108$ vs. $h_{45-50} = 0.121$, with only $0.71\%$ of trades closing between 43m and 47m).
5. **Anti-Martingale / Inverted Martingale Sizing**:
   - Falsified by binomial Markov transition testing. Scale-up to 0.02 lots occurred after a win in $81.8\%$ of cases, which is statistically indistinguishable from the background baseline win rate of $86.76\%$ ($p = 0.523$). Lot sizing is statistically independent of prior trade P&L.

---

## 4. Unresolved Core Questions for Phase 8D

The central scientific problem remains: **What information was the original system responding to at the moment of entry?**

Phase 8D will systematically investigate four mutually exclusive hypotheses:
1. **Hypothesis A**: A deterministic market-price trigger that has not yet been discovered.
2. **Hypothesis B**: A short-lived microstructure/event sequence operating on sub-minute tick time.
3. **Hypothesis C**: A hidden state/history-dependent rule governing execution eligibility.
4. **Hypothesis D**: Unobserved / exogenous information (external signal stream, proprietary feed, scheduled economic calendar, or discretionary manual execution).
