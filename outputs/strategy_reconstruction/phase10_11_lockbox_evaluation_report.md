# Phase 10/11 Forensic Lockbox Evaluation & Entry-Rule Analysis

## 1. Frozen Model Specification & Cryptographic Certificate
- **Selected Model**: `M3` (Clock Harmonics + 8 Causal Microstructure Features)
- **Regularization Parameter**: $\lambda = 1.0$
- **Discovery Epochs**: 317
- **Model Freeze Hash**: `5159dcedb0c3c3c3d4bca14b9c94841434fc3cf80f5065d07188609c1a3a2718`
- **Status**: **VERIFIED OUT-OF-SAMPLE EVALUATION (ZERO RETRAINING / ZERO TUNING)**

### Frozen Model Coefficients (Beta)
| Feature Name | Frozen $\beta$ | Discovery Mean | Discovery Std |
|:---|---:|---:|---:|
| `utc_hour` | -0.153427 | 10.2818 | 3.3768 |
| `utc_minute` | -0.125536 | 29.5152 | 17.3835 |
| `day_of_week` | -0.000000 | 1.8849 | 1.4024 |
| `is_monday` | -0.000000 | 0.2250 | 0.4176 |
| `is_friday` | +0.000000 | 0.1614 | 0.3679 |
| `jump_z` | +0.305755 | 0.9503 | 1.0943 |
| `disp30` | -0.180519 | 10.7516 | 10.8889 |
| `tick_rate_30` | +0.310776 | 5.0526 | 2.9176 |
| `tick_rate_ratio` | -0.004594 | 1.0781 | 0.6940 |
| `spread_now` | +1.955071 | 0.6974 | 0.1840 |
| `spread_ratio` | -1.955256 | 1.0495 | 0.2763 |
| `ret5` | -0.034260 | -0.0004 | 0.6915 |
| `n_ticks_300` | -0.475968 | 1491.1126 | 827.6492 |

## 2. Lockbox Out-of-Sample Performance
- **Lockbox Records**: 102
- **Lockbox Decision Epochs**: 102
- **Strata Evaluated**: 99 (Excluded: 3)
- **Out-of-Sample Log-Likelihood / Case**: `-5.1777`
- **Null Baseline Log-Likelihood / Case**: `-5.7304`
- **Out-of-Sample Improvement**: **`+0.5527` log-lik per decision epoch**
- **Mean Case Percentile within Stratum**: `77.91%`
- **Top-10% Capture Rate**: `56.6%` of actual entries ranked in top decile
- **Top-5% Capture Rate**: `44.4%` of actual entries ranked in top 5th percentile
- **Top-1% Capture Rate**: `22.2%` of actual entries ranked in top 1st percentile


## 3. Case vs. Control Score Separation
- **Case Mean Linear Score**: `+0.8113` (Median: `+0.8611`)
- **Control Mean Linear Score**: `+0.0501` (Median: `-0.0286`)
- **Effect Size (Cohen's d)**: `1.0587` standard deviations
- **Mann-Whitney U Test p-value**: `5.9409e-21` (Statistically significant separation)


## 4. Decision Threshold Calibration & Enrichment Curve
| Control Baseline Percentile | Score Threshold $\tau$ | Case Capture Rate (TPR) | Control Trigger Rate (FPR) | Precision | Enrichment Ratio |
|---:|---:|---:|---:|---:|---:|
| 50.0% | -0.0286 | 80.8% | 50.00% | 0.49% | **1.6x** |
| 75.0% | +0.2927 | 70.7% | 25.00% | 0.85% | **2.8x** |
| 90.0% | +0.7307 | 53.5% | 10.00% | 1.60% | **5.4x** |
| 95.0% | +1.0072 | 43.4% | 5.00% | 2.57% | **8.7x** |
| 98.0% | +1.2439 | 30.3% | 2.00% | 4.41% | **15.1x** |
| 99.0% | +1.4334 | 23.2% | 1.00% | 6.59% | **23.2x** |
| 99.5% | +1.5722 | 19.2% | 0.50% | 10.44% | **38.3x** |
| 99.9% | +1.9510 | 7.1% | 0.10% | 17.50% | **69.7x** |

## 5. Microstructure Feature Significance on Lockbox
| Feature | Case Mean | Control Mean | Difference | p-value |
|:---|---:|---:|---:|---:|
| `utc_hour` | 8.0303 | 9.9136 | -1.8833 | 1.2185e-04 |
| `utc_minute` | 26.7576 | 29.5824 | -2.8248 | 1.1784e-01 |
| `day_of_week` | 2.0606 | 2.0709 | -0.0103 | 9.4176e-01 |
| `is_monday` | 0.1717 | 0.1723 | -0.0006 | 9.8783e-01 |
| `is_friday` | 0.2020 | 0.2108 | -0.0088 | 8.2924e-01 |
| `jump_z` | 0.8080 | 0.7385 | +0.0695 | 4.3320e-01 |
| `disp30` | 8.5428 | 8.9156 | -0.3728 | 5.4474e-01 |
| `tick_rate_30` | 3.8828 | 4.3673 | -0.4845 | 2.4236e-02 |
| `tick_rate_ratio` | 1.4504 | 1.0892 | +0.3613 | 2.7433e-02 |
| `spread_now` | 0.6729 | 0.6155 | +0.0574 | 6.4556e-06 |
| `spread_ratio` | 0.9325 | 0.9241 | +0.0084 | 6.2269e-01 |
| `ret5` | -0.0337 | -0.0023 | -0.0313 | 5.9663e-01 |
| `n_ticks_300` | 1055.8889 | 1284.4184 | -228.5296 | 3.1993e-04 |

## 6. Synthesized Candidate Entry Rules
### Rule 1 Linear Score Top1Pct
- **Description**: Linear score eta >= 99th percentile of control baseline
- **Condition**: `eta >= 1.4334`
- **Case Capture (Recall)**: `23.2%`
- **Control Baseline Trigger Rate**: `1.00%`

### Rule 2 Spread Compression Jump
- **Description**: Spread compressed (spread_ratio <= 1.0) with positive directional tick acceleration (jump_z >= 1.5)
- **Case Capture (Recall)**: `8.1%`
- **Control Baseline Trigger Rate**: `7.23%`

### Rule 3 Microstructure Burst
- **Description**: High 30s tick rate burst (tick_rate_ratio >= 1.5) with low relative spread (spread_ratio <= 0.95)
- **Case Capture (Recall)**: `7.1%`
- **Control Baseline Trigger Rate**: `2.99%`
