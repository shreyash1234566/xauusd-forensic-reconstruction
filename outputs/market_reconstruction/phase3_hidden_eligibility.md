# Phase 3 hidden eligibility reconstruction

## Small interpretable eligibility score

The score family combines clock post-window indicators, pre-entry trade/cooldown state, completed-bar event count and a small location set. The models are L1 logistic or depth-3 trees, fitted and threshold-calibrated only on prior chronological history.

| hypothesis | candidate_signals | tp | fp | fn | precision | recall | f1 | roc_auc | pr_auc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P3 constrained clock+state tree | 6463 | 12 | 6451 | 294 | 0.0018567 | 0.039216 | 0.0024009 | 0.59527 | 0.0019155 |
| P3 sparse clock+state eligibility | 3642 | 9 | 3633 | 297 | 0.0024712 | 0.029412 | 0.0020075 | 0.60499 | 0.0023522 |

The best tested Phase 3 candidate is **H1 M30 boundary / bar-close proxy** with OOS precision 0.00383, recall 0.09477, mean F1 0.00734, and 7,573 signals. It remains far too non-selective for event-level replication.
