import numpy as np
import pandas as pd
import pytest

from reverse_trade.reconstruction.policy_ast import (
    Action,
    AndCondition,
    CrossesAboveCondition,
    CrossesBelowCondition,
    Policy,
    PriceDistanceExit,
    StateCondition,
    ThresholdCondition,
    TimeExit,
    TimeWindowCondition,
    TrailingStopExit,
)
from reverse_trade.reconstruction.replay import Quote, ReplayEngine
from reverse_trade.reconstruction.search import evaluate_policy
from reverse_trade.reconstruction.state_search import (
    enumerate_stateful_policies,
    search_stateful_policies,
)
from reverse_trade.reconstruction.synthesis import (
    SearchBudget,
    enumerate_crossing_policies,
    enumerate_exit_rules,
    enumerate_t0_policies,
    enumerate_t1_conjunction_policies,
    enumerate_time_window_policies,
    synthesize_beam_search,
    threshold_grid,
)


@pytest.fixture
def synthetic_market_data() -> tuple[list[Quote], pd.DataFrame, pd.DataFrame]:
    times = pd.date_range("2026-01-01 14:00:00", periods=60, freq="10s", tz="UTC")
    quotes = [
        Quote(t, 2000.0 + i * 0.1, 2000.1 + i * 0.1)
        for i, t in enumerate(times)
    ]

    features = pd.DataFrame({
        "decision_time_utc": times,
        "hour_utc": [t.hour for t in times],
        "day_of_week": [t.dayofweek for t in times],
        "ret5": np.linspace(-0.002, 0.002, len(times)),
        "prev_ret5": np.roll(np.linspace(-0.002, 0.002, len(times)), 1),
        "spread": [0.1] * len(times),
        "feature_status": "observed",
    })

    # Observed trade epochs at indices 10 and 30
    observed_epochs = pd.DataFrame([
        {"decision_time_utc": times[10], "side": "Buy", "volume": 0.01},
        {"decision_time_utc": times[30], "side": "Buy", "volume": 0.01},
    ])

    return quotes, features, observed_epochs


def test_threshold_grid():
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    grid = threshold_grid(values, maximum=5)
    assert len(grid) <= 5
    assert all(np.isfinite(x) for x in grid)
    assert threshold_grid([], 5) == []


def test_enumerate_t0_and_crossing_policies(synthetic_market_data):
    quotes, features, _ = synthetic_market_data
    budget = SearchBudget(max_thresholds_per_feature=3, cooldowns_seconds=(0.0,), volumes=(0.01,))

    t0_cands = enumerate_t0_policies(features, features=["ret5"], budget=budget)
    assert len(t0_cands) > 0
    assert all(isinstance(p.entry, ThresholdCondition) for p in t0_cands)

    crossing_cands = enumerate_crossing_policies(features, features=["ret5"], budget=budget)
    assert len(crossing_cands) > 0
    assert any(isinstance(p.entry, CrossesAboveCondition) for p in crossing_cands)
    assert any(isinstance(p.entry, CrossesBelowCondition) for p in crossing_cands)


def test_enumerate_t1_and_time_window_policies(synthetic_market_data):
    quotes, features, _ = synthetic_market_data
    budget = SearchBudget(max_thresholds_per_feature=2, max_conjunction_pairs=5)

    t1_cands = enumerate_t1_conjunction_policies(features, feature_pairs=[("ret5", "spread")], budget=budget)
    assert len(t1_cands) > 0
    assert all(isinstance(p.entry, AndCondition) for p in t1_cands)

    base_conds = [ThresholdCondition("ret5", ">", 0.0)]
    tw_cands = enumerate_time_window_policies(features, base_conditions=base_conds, budget=budget)
    assert len(tw_cands) > 0
    assert all(isinstance(p.entry, AndCondition) for p in tw_cands)


def test_enumerate_exit_rules():
    exits = enumerate_exit_rules()
    assert len(exits) >= 10
    assert any(isinstance(e, TimeExit) for e in exits)
    assert any(isinstance(e, PriceDistanceExit) for e in exits)
    assert any(isinstance(e, TrailingStopExit) for e in exits)


def test_synthesize_beam_search(synthetic_market_data):
    quotes, features, observed_epochs = synthetic_market_data
    budget = SearchBudget(max_thresholds_per_feature=3, max_conjunction_pairs=3)

    best_beam = synthesize_beam_search(
        features,
        quotes,
        observed_epochs,
        features=["ret5", "spread"],
        beam_width=5,
        max_depth=2,
        budget=budget,
    )
    assert len(best_beam) > 0
    assert len(best_beam) <= 5


def test_stateful_policy_enumeration_and_search(synthetic_market_data):
    quotes, features, observed_epochs = synthetic_market_data
    budget = SearchBudget(max_thresholds_per_feature=2)

    fsm_policies = enumerate_stateful_policies(features, features=["ret5"], num_states=2, budget=budget)
    assert len(fsm_policies) > 0
    assert all(p.state_transitions for p in fsm_policies)

    summaries = search_stateful_policies(
        features, quotes, observed_epochs, features=["ret5"], num_states=2, top_k=3, budget=budget
    )
    assert len(summaries) <= 3
    assert len(summaries) > 0


def test_stateful_replay_state_transitions():
    times = pd.date_range("2026-01-01 12:00:00", periods=5, freq="10s", tz="UTC")
    quotes = [Quote(t, 2000.0, 2000.1) for t in times]
    decisions = pd.DataFrame({
        "decision_time_utc": times,
        "feature_val": [1.0, 10.0, 20.0, 30.0, 40.0],
        "feature_status": "observed",
    })

    # Policy triggers on state 0 and feature_val > 5.0, transitions to state 1
    cond = AndCondition((
        StateCondition(expected_state=0),
        ThresholdCondition("feature_val", ">", 5.0),
    ))
    policy = Policy(
        cond,
        Action.OPEN_BUY,
        volume=0.01,
        exit_rule=TimeExit(holding_seconds=10.0),
        state_transitions={"Buy": 1, "Sell": 1},
    )

    engine = ReplayEngine(policy)
    trades, trace = engine.run(quotes, decisions)

    # Should execute exactly 1 trade at index 1 and transition to state 1
    assert len(trades) == 1
    assert trades.iloc[0].open_time_utc == times[1]
