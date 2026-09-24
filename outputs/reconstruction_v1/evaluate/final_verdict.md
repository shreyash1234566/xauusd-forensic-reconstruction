# Algorithm Reconstruction Final Verdict Report

## 1. Reconstruction Verdict & Claim Level
- **Assigned Verdict:** `tested_family_failure`
- **Explanation:** Searched grammar tiers failed to explain observed ledger epochs (best F1=0.0048, loss=0.9976).

## 2. Quantitative Summary
- **Total Candidates Evaluated:** 40
- **Observational Equivalence Classes:** 5
- **Top Candidate ID:** `cand_0000`
- **Top Candidate F1 Score:** 0.0048
- **Top Candidate Entry Error Loss:** 0.9976
- **Supported Observed Epochs:** 420
- **Unsupported / Gap Epochs:** 0

## 3. Surviving Equivalence Classes
| Class ID | Size | Representative Candidate | Mean F1 | Mean Loss | Member Candidates |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `EQ-001` | 12 | `cand_0000` | 0.0048 | 0.9976 | cand_0000, cand_0001, cand_0002, cand_0003, cand_0004, ... (+7 more) |
| `EQ-002` | 4 | `cand_0008` | 0.0048 | 0.9976 | cand_0008, cand_0009, cand_0010, cand_0011 |
| `EQ-003` | 4 | `cand_0012` | 0.0048 | 0.9976 | cand_0012, cand_0013, cand_0014, cand_0015 |
| `EQ-004` | 4 | `cand_0016` | 0.0048 | 0.9976 | cand_0016, cand_0017, cand_0018, cand_0019 |
| `EQ-005` | 16 | `cand_0024` | 0.0000 | 1.0000 | cand_0024, cand_0025, cand_0026, cand_0027, cand_0028, ... (+11 more) |

## 4. Methodological Invariants & Guarantees
- **Zero Lookahead Leakage:** Feature evaluations strictly guarantee $t_{\text{quote}} < t_{\text{decision}}$.
- **Independent Replay Simulation:** Replay engine executes autonomously without borrowing ledger state.
- **Separation of Evidence:** Observed coverage is strictly separated from gap periods.
