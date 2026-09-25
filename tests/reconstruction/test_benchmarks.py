import pandas as pd
import pytest

from reverse_trade.reconstruction.benchmarks import (
    PLANTED_BENCHMARK_REGISTRY,
    planted_bar_threshold_policy,
    planted_clock_only_policy,
    planted_conjunction_policy,
    planted_cooldown_state_policy,
    planted_null_stochastic_policy,
    planted_observational_equivalence_pair,
    planted_out_of_family_policy,
    planted_pending_delayed_fill_policy,
    planted_regime_switching_policy,
    planted_reversal_policy,
    planted_tick_first_crossing_policy,
    planted_trailing_exit_policy,
    run_single_planted_benchmark,
)
from reverse_trade.reconstruction.replay import Quote


@pytest.fixture
def synthetic_market_data() -> tuple[list[Quote], pd.DataFrame]:
    times = pd.date_range("2026-01-01T14:00:00Z", periods=20, freq="s")
    quotes = [Quote(t, 100.0 + i * 0.1, 100.1 + i * 0.1) for i, t in enumerate(times)]
    features = pd.DataFrame({
        "decision_time_utc": times,
        "hour_utc": [14] * 20,
        "day_of_week": [3] * 20,
        "ret5": [0.0, 0.002, 0.0, -0.003, 0.0, 0.0015, 0.0, 0.0] + [0.0] * 12,
        "prev_ret5": [0.0, 0.0, 0.002, 0.0, -0.003, 0.0, 0.0015, 0.0] + [0.0] * 12,
        "bar_ret5": [0.0, 0.003, 0.0, 0.0, 0.004, 0.0] + [0.0] * 14,
        "spread": [0.1] * 20,
        "volatility": [0.001] * 10 + [0.006] * 10,
        "decision_index": list(range(20)),
        "feature_status": ["observed"] * 20,
        "support_status": ["observed"] * 20,
    })
    return quotes, features


def test_all_12_planted_families_instantiate_cleanly() -> None:
    assert len(PLANTED_BENCHMARK_REGISTRY) == 12
    for name, generator in PLANTED_BENCHMARK_REGISTRY.items():
        policy_or_pair = generator()
        if isinstance(policy_or_pair, tuple):
            assert len(policy_or_pair) == 2
            assert all(p.complexity() > 0 for p in policy_or_pair)
        else:
            assert policy_or_pair.complexity() > 0
            assert policy_or_pair.to_dict() is not None


def test_clock_only_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("clock_only", quotes, features)
    assert result.f1_score == 1.0
    assert result.entry_error_loss == 0.0
    assert result.exact_match is True


def test_bar_threshold_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("bar_threshold", quotes, features)
    assert result.f1_score == 1.0
    assert result.entry_error_loss == 0.0
    assert result.exact_match is True


def test_tick_first_crossing_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("tick_first_crossing", quotes, features)
    assert result.f1_score == 1.0
    assert result.exact_match is True


def test_reversal_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("reversal", quotes, features)
    assert result.f1_score == 1.0
    assert result.entry_error_loss == 0.0
    assert result.exact_match is True


def test_conjunction_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("conjunction", quotes, features)
    assert result.f1_score == 1.0
    assert result.exact_match is True


def test_cooldown_state_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("cooldown_state", quotes, features)
    assert result.f1_score == 1.0
    assert result.exact_match is True


def test_pending_limit_does_not_claim_recovery_without_a_fill(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("pending_delayed_fill", quotes, features)
    assert result.detail["num_trades_observed"] == 0
    assert result.f1_score == 0.0


def test_trailing_exit_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("trailing_exit", quotes, features)
    assert result.f1_score == 1.0
    assert result.exact_match is True


def test_regime_switching_benchmark_recovery(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("regime_switching", quotes, features)
    assert result.f1_score == 1.0
    assert result.exact_match is True


def test_observational_equivalence_pair(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("observational_equivalence", quotes, features)
    assert result.exact_match is True
    assert result.f1_score == 1.0


def test_null_stochastic_benchmark_behavior(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("null_stochastic", quotes, features)
    assert result.in_grammar is False


def test_out_of_family_benchmark_behavior(synthetic_market_data) -> None:
    quotes, features = synthetic_market_data
    result = run_single_planted_benchmark("out_of_family", quotes, features)
    assert result.in_grammar is False
