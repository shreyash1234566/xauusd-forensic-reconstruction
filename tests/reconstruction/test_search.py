import pandas as pd

from reverse_trade.reconstruction.policy_ast import Action, Policy, PriceDistanceExit, ThresholdCondition
from reverse_trade.reconstruction.replay import Quote
from reverse_trade.reconstruction.search import evaluate_policy, rank_evaluations


def test_evaluator_reports_unknown_support_separately_and_ranks_candidates() -> None:
    policy = Policy(ThresholdCondition("ret5", ">", 0.0), Action.OPEN_BUY, exit_rule=PriceDistanceExit(take_profit=1.0))
    quotes = [
        Quote(pd.Timestamp("2026-01-01T00:00:00Z"), 100.0, 101.0),
        Quote(pd.Timestamp("2026-01-01T00:00:05Z"), 102.0, 103.0),
    ]
    features = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:05Z"], utc=True),
        "ret5": [0.1, 0.1], "feature_status": ["observed", "observed"],
        "support_status": ["observed", "unknown"],
    })
    epochs = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:05Z"], utc=True),
        "side": ["Buy", "Buy"], "volume": [0.01, 0.01],
    })
    result = evaluate_policy("candidate", policy, quotes, features, epochs)
    assert result.metrics["whole_ledger_epochs"] == 2
    assert result.metrics["unsupported_observed_epochs"] == 1
    assert result.metrics["tp"] == 1
    assert rank_evaluations([result]).loc[0, "candidate_id"] == "candidate"
