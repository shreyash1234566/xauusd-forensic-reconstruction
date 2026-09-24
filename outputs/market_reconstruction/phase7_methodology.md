# Phase 7: Full 423-Trade Market / Chart Identification Methodology

## 1. Objective & Mathematical Framework

The objective of Phase 7 is to establish the ground-truth physical market, historical price feed, contract specifications, and timezone mapping governing the canonical 423-trade execution dataset (`data/raw/trades_raw.tsv`) operating on `XAUUSD.f`.

```
========================================================================================
                          PHASE 7 RECONSTRUCTION ARCHITECTURE
========================================================================================
  [ 423 Canonical Trades ] ──► [ SHA256 Invariant Freeze ]
                                         │
                                         ▼
  [ Global Timezone Grid ] ──► [ UTC-12 to UTC+14 Sweep & DST EEST/EET Optimization ]
                                         │
                                         ▼
  [ Stored Price Role ]    ──► [ H_ENTRY vs H_EXIT Two-Sided Residual Minimization ]
                                         │
                                         ▼
  [ Contract Multiplier ]  ──► [ Multiplier Optimization: C in [1, 1000], C*=100 oz/lot ]
                                         │
                                         ▼
  [ Multi-Feed Benchmark ] ──► [ Dukascopy Spot, RoboForex ProFix, Futures, Controls ]
                                         │
                                         ▼
  [ Full P&L Replication ] ──► [ Reconstruct Sum(PnL_i) = $1,451.22 & Residual Analysis ]
========================================================================================
```

---

## 2. Invariant Equations & Price Semantics

### 2.1 Stored Price Hypotheses & Counterpart Formulas

For each trade $i \in \{1, \dots, 423\}$ with recorded parameters $(t_i^{\text{open}}, t_i^{\text{close}}, \text{side}_i, v_i, P_i^{\text{stored}}, \text{PnL}_i)$:

#### Hypothesis $H_{\text{ENTRY}}$ (Stored Price = Entry Price)
* **BUY Trade**:
  $$P_{\text{exit}}^{\text{implied}} = P_{\text{stored}} + \frac{\text{PnL}}{v \cdot C}$$
* **SELL Trade**:
  $$P_{\text{exit}}^{\text{implied}} = P_{\text{stored}} - \frac{\text{PnL}}{v \cdot C}$$

#### Hypothesis $H_{\text{EXIT}}$ (Stored Price = Exit Price)
* **BUY Trade**:
  $$P_{\text{entry}}^{\text{implied}} = P_{\text{stored}} - \frac{\text{PnL}}{v \cdot C}$$
* **SELL Trade**:
  $$P_{\text{entry}}^{\text{implied}} = P_{\text{stored}} + \frac{\text{PnL}}{v \cdot C}$$

---

## 3. Two-Sided Market Execution Logic

Accounting for broker bid/ask quotes and fixed spread $S$:
* **BUY Entry**: Executed at $\text{Ask} = \text{Bid} + S$.
* **BUY Exit**: Executed at $\text{Bid} = \text{Bid}$.
* **SELL Entry**: Executed at $\text{Bid} = \text{Bid}$.
* **SELL Exit**: Executed at $\text{Ask} = \text{Bid} + S$.

### Theoretical Gross & Net Reconstructed P&L
$$\widehat{\text{PnL}}_i = \begin{cases}
(P_{\text{exit}}^{\text{Bid}} - P_{\text{entry}}^{\text{Ask}}) \cdot v_i \cdot C & \text{for BUY} \\[6pt]
(P_{\text{entry}}^{\text{Bid}} - P_{\text{exit}}^{\text{Ask}}) \cdot v_i \cdot C & \text{for SELL}
\end{cases}$$

---

## 4. Multi-Timezone Transformation Matrix

The historical trade timestamps follow Eastern European Time with Daylight Saving Time (**EET/EEST**):
* **Summer Period (EEST)**: $\Delta t = \text{UTC}+3 \implies t_{\text{UTC}} = t_{\text{recorded}} - 3\text{h}$
* **Winter Period (EET)**: $\Delta t = \text{UTC}+2 \implies t_{\text{UTC}} = t_{\text{recorded}} - 2\text{h}$
* Transitions occurred on **2025-10-26 03:00:00** and **2026-03-29 03:00:00**.
