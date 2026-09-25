import pandas as pd
import pytest

from reverse_trade.reconstruction.matching import MatchConfig, match_entries
from reverse_trade.reconstruction.policy_ast import Action, Policy, PriceDistanceExit, ThresholdCondition, TimeExit
from reverse_trade.reconstruction.replay import Quote, ReplayEngine
from reverse_trade.reconstruction.observation import ObservationScenario


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


def test_matching_rejects_wrong_direction_and_size_by_default() -> None:
    observed = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "side": ["Buy"], "volume": [0.02],
    })
    predicted = pd.DataFrame({
        "open_time_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "side": ["Sell"], "volume": [0.01],
    })
    _, summary = match_entries(observed, predicted)
    assert (summary["tp"], summary["fp"], summary["fn"]) == (0, 1, 1)


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


def test_buy_limit_does_not_fill_when_ask_remains_above_limit() -> None:
    policy = Policy(ThresholdCondition("signal", ">", 0.0), Action.PLACE_LIMIT)
    times = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z"], utc=True)
    quotes = [Quote(times[0], 100.0, 101.0), Quote(times[1], 100.5, 102.0)]
    decisions = pd.DataFrame({"decision_time_utc": [times[0]], "signal": [1.0], "feature_status": ["observed"]})
    trades, _ = ReplayEngine(policy).run(quotes, decisions)
    assert trades.empty


def test_policy_ast_round_trips_nested_conditions() -> None:
    from reverse_trade.reconstruction.policy_ast import AndCondition, NotCondition

    policy = Policy(
        AndCondition((ThresholdCondition("ret5", ">", 0.1), NotCondition(ThresholdCondition("spread", ">", 0.5)))),
        Action.OPEN_BUY,
    )
    restored = Policy.from_dict(policy.to_dict())
    assert restored.to_dict()["entry"] == policy.to_dict()["entry"]


def test_persistence_condition_round_trips() -> None:
    from reverse_trade.reconstruction.policy_ast import PersistsCondition

    policy = Policy(PersistsCondition("ret5", ">", 0.1, periods=3), Action.OPEN_BUY)
    assert Policy.from_dict(policy.to_dict()).to_dict()["entry"] == policy.to_dict()["entry"]


def test_delayed_market_order_waits_for_first_quote_after_due_time() -> None:
    policy = Policy(ThresholdCondition("signal", ">", 0.0), Action.OPEN_BUY)
    times = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:00:02Z"], utc=True)
    quotes = [Quote(times[0], 100.0, 101.0), Quote(times[1], 102.0, 103.0)]
    decisions = pd.DataFrame({"decision_time_utc": [times[0]], "signal": [1.0], "feature_status": ["observed"]})
    scenario = ObservationScenario("delay", market_order_delay=pd.Timedelta(seconds=1))
    trades, trace = ReplayEngine(policy, scenario).run(quotes, decisions)
    assert len(trades) == 1
    assert trades.iloc[0].open_time_utc == times[1]
    assert trades.iloc[0].open_price == 103.0
    assert "fill" in set(trace.event_type)
