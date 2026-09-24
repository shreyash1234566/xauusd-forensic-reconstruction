# Phase 12 — Exact Deterministic Entry-Rule Identity Audit Report

## Executive Summary & Final Identity Verdict

- **OPERATIONAL IDENTITY VERDICT:** `FAIL`
- **Exact Decision Points Evaluated ($U = E \cup F$):** $N_U = 206,066$
- **Observed Canonical Decision Epochs ($E$):** $N_E = 420$
- **Complete Eligible Historical Non-Entry Universe ($F$):** $N_F = 205,646$
- **Disjoint Check ($E \cap F$):** 0 overlapping decision timestamps

---

## 1. Scope & Data Universe Resolution

### Historical Scopes Comparison
- **16,370 observations:** Matched 1:160 sampled risk-set controls from the lockbox partition evaluation.
- **32,646 observations:** Matched 1:320 sampled risk-set controls (102 cases + 32,544 controls) from local sensitivity designs.
- **205,646 observations ($F$):** Complete, exhaustive non-entry universe of all flat candidate minutes across the full historical decision panel ($05:00 \le \text{hour} \le 16:00$ UTC) excluding trade intervals $[\text{open}, \text{close})$ of all 423 canonical records.
- **206,066 observations ($U$):** Total decision points evaluated for entry triggering ($420 \text{ cases} + 205,646 \text{ controls}$).

---

## 2. Rule Specification & Discovery-Frozen Provenance

- **Model Specification:** M3 Linear Predictor with 13 standardized causal features (5 time/calendar + 8 microstructure tick features).
- **Rule Definition:** $R_1(t) = \mathbb{I}(\eta(t) \ge \tau_{\text{disc}})$
- **Threshold Origin:** 99.0th percentile evaluated **strictly on Discovery controls ($N = 115,134$)**.
- **Frozen Threshold Value:** $\tau_{\text{disc}} = 1.533564$
- **Status:** **FULLY DISCOVERY-FROZEN** (Zero lockbox controls or future labels used in calibration).

---

## 3. Complete Ledger Confusion Matrix & Partition Performance

### Summary Table

| Partition | Total Points | Cases ($E$) | Controls ($F$) | TP | FN | FP | TN | Recall | Precision | F1 Score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Discovery** | 154,667 | 317 | 154,350 | 31 | 286 | 403 | 153,947 | 9.78% | 7.14% | 0.0826 |
| **Buffer** | 1,432 | 1 | 1,431 | 0 | 1 | 5 | 1,426 | 0.00% | 0.00% | 0.0000 |
| **Lockbox (OOS)** | 49,967 | 102 | 49,865 | 19 | 83 | 77 | 49,788 | 18.63% | 19.79% | 0.1919 |
| **COMPLETE LEDGER ($U$)** | **206,066** | **420** | **205,646** | **50** | **370** | **485** | **205,161** | **11.90%** | **9.35%** | **0.1047** |

---

## 4. Exact Timing & Causality Verification

1. **Exact Timestamp Match Resolution:** Evaluated at exact millisecond/second epoch anchor timestamps (`offset_seconds = 0`).
2. **Strict Causality Verification:** Every tick utilized in microstructural feature calculation satisfies $t_{\text{tick}} < t_{\text{decision}}$. Look-ahead detected = **NO**.
3. **Zero Target Leakage:** Prediction $\eta(t)$ is computed strictly from pre-decision market features prior to evaluating identity against $E$. Target leakage detected = **NO**.

---

## 5. Mismatch Catalogs

- **Actual Entries Not Triggered (FN):** `370` records saved to `outputs/strategy_reconstruction/phase12_actual_entry_not_triggered.csv`.
- **Non-Trades Triggered (FP):** `485` records saved to `outputs/strategy_reconstruction/phase12_nontrade_triggered.csv`.
