import pandas as pd

from reverse_trade.reconstruction.matching import MatchConfig, match_entries
from reverse_trade.reconstruction.policy_ast import Action, Policy, PriceDistanceExit, ThresholdCondition, TimeExit
from reverse_trade.reconstruction.replay import Quote, ReplayEngine


def test_replay_uses_candidate_state_and_respects_unknown_features() -> None:
    policy = Policy(ThresholdCondition("ret5", ">", 0.0), Action.OPEN_BUY, cooldown_seconds=30.0)
    quotes = [
        Quote(pd.Timestamp("2026-01-01T00:00:00Z"), 100.0, 101.0),
        Quote(pd.Timestamp("2026-01-01T00:00:10Z"), 101.0, 102.0),
    ]
    decisions = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z"], utc=True),
        "ret5": [0.01, 0.01], "feature_status": ["observed", "unknown"],
    })
    trades, trace = ReplayEngine(policy).run(quotes, decisions)
    assert len(trades) == 1
    assert trades.iloc[0].open_price == 101.0
    assert trace.loc[trace["event_type"].eq("decision"), "action"].tolist() == ["open_buy", "none"]


def test_matching_is_one_to_one_not_greedy_reuse() -> None:
    observed = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:10Z"], utc=True), "side": ["Buy"], "volume": [0.01]
    })
    predicted = pd.DataFrame({
        "open_time_utc": pd.to_datetime(["2026-01-01T00:00:09Z", "2026-01-01T00:00:11Z"], utc=True),
        "side": ["Buy", "Buy"], "volume": [0.01, 0.01]
    })
    table, summary = match_entries(observed, predicted, MatchConfig(entry_tolerance=pd.Timedelta(seconds=2)))
    assert summary == {"tp": 1, "fp": 1, "fn": 0, "observed": 1, "predicted": 2, "precision": 0.5, "recall": 1.0, "f1": 2 / 3}
    assert set(table["status"]) == {"tp", "fp"}


def test_replay_exits_from_its_own_position_state_with_bid_ask_accounting() -> None:
    policy = Policy(
        ThresholdCondition("ret5", ">", 0.0), Action.OPEN_BUY,
        exit_rule=PriceDistanceExit(take_profit=1.0), cooldown_seconds=30.0,
    )
    quotes = [
        Quote(pd.Timestamp("2026-01-01T00:00:00Z"), 100.0, 101.0),
        Quote(pd.Timestamp("2026-01-01T00:00:05Z"), 102.0, 103.0),
    ]
    decisions = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:05Z"], utc=True),
        "ret5": [0.1, 0.1], "feature_status": ["observed", "observed"],
    })
    trades, trace = ReplayEngine(policy).run(quotes, decisions)
    assert len(trades) == 1
    assert trades.iloc[0].open_price == 101.0
    assert trades.iloc[0].close_price == 102.0
    assert trades.iloc[0].close_reason == "take_profit"
    assert "exit" in set(trace["event_type"])
