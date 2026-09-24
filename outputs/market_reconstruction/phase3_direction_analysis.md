# Phase 3 direction inside clock windows

Direction is evaluated only among observed entry bars inside the M30 post-boundary proxy window, using pre-entry event polarity and location. This changes the conditioning question from all-market direction prediction to “given potential clock interest, what selects Buy versus Sell?”

| fold | train_n | test_n | accuracy | roc_auc | buy_pr_auc |
| --- | --- | --- | --- | --- | --- |
| 1 | 17 | 11 | 0.36364 | 0.36667 | 0.4548 |
| 2 | 28 | 16 | 0.3125 | 0.26984 | 0.45672 |
| 3 | 44 | 13 | 0.53846 | 0.275 | 0.36051 |
| 4 | 57 | 9 | 0.55556 | 0.7 | 0.80833 |
| 5 | 66 | 7 | 0.42857 | 0.16667 | 0.36508 |

Small fold counts and M1 path ambiguity prevent treating any apparent discrimination as a direction-rule reconstruction.
