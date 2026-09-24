# Placebo Sensitivity & Robustness Calibration Report

## 1. Placebo Block-Permutation Results

| Candidate ID | Real F1 | Real Loss | Null F1 Mean ± Std | Null Loss Mean | p-Value (F1) | Significant? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `cand_0000` | 0.0048 | 0.9976 | 0.0000 ± 0.0000 | 1.0000 | 0.0000 | **YES** (p < 0.05) |

## 2. Statistical Interpretation
- The null distribution is generated via temporal block shifts across the continuous market path.
- A candidate is statistically significant only if real F1 exceeds null F1 distribution by >2 standard deviations ($p < 0.05$).
