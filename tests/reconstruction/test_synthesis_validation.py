import pandas as pd
import pytest

from reverse_trade.reconstruction.benchmarks import run_threshold_recovery_benchmark
from reverse_trade.reconstruction.policy_ast import Action
from reverse_trade.reconstruction.replay import Quote
from reverse_trade.reconstruction.synthesis import SearchBudget, enumerate_t0_policies
from reverse_trade.reconstruction.validation import assert_causal_feature_frame, make_expanding_folds


def test_t0_synthesis_is_finite_and_serializable() -> None:
    frame = pd.DataFrame({"ret5": [-0.1, 0.0, 0.1]})
    candidates = enumerate_t0_policies(
        frame, features=["ret5"],
        budget=SearchBudget(max_thresholds_per_feature=2, directions=(Action.OPEN_BUY,), cooldowns_seconds=(0.0,), volumes=(0.01,)),
    )
    assert len(candidates) == 4
    assert all(candidate.to_dict()["complexity"] > 0 for candidate in candidates)


def test_validation_detects_feature_boundary_leakage() -> None:
    frame = pd.DataFrame({
        "decision_time_utc": pd.to_datetime(["2026-01-01T00:00:01Z"], utc=True),
        "maximum_input_time": pd.to_datetime(["2026-01-01T00:00:01Z"], utc=True),
    })
    with pytest.raises(ValueError, match="at or after"):
        assert_causal_feature_frame(frame)
    times = pd.Series(pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC"))
    assert len(make_expanding_folds(times, minimum_train_events=4, outer_blocks=2)) == 2


def test_planted_t0_threshold_recovery_uses_full_replay_path() -> None:
    quote_times = pd.date_range("2026-01-01T00:00:00Z", periods=8, freq="s")
    quotes = [Quote(time, 100.0 + index, 101.0 + index) for index, time in enumerate(quote_times)]
    features = pd.DataFrame({
        "decision_time_utc": quote_times,
        "ret5": [0.0, 0.002, 0.0, 0.003, 0.0, 0.004, 0.0, 0.0],
        "feature_status": ["observed"] * len(quote_times),
        "support_status": ["observed"] * len(quote_times),
    })
    ranking, evaluations = run_threshold_recovery_benchmark(quotes, features)
    assert ranking.iloc[0]["f1"] == 1.0
    assert ranking.iloc[0]["entry_error_loss"] == 0.0
    assert len(evaluations) > 1
