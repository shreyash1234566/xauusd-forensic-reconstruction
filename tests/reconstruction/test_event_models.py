import numpy as np
import pandas as pd
import pytest

from reverse_trade.reconstruction.event_models import (
    B0HomogeneousPoissonModel,
    B1DiurnalCalendarModel,
    B2CompletedBarModel,
    B3CausalTickModel,
    B4JointBarTickModel,
    B5HawkesSelfExcitingModel,
    calculate_bits_per_event,
    evaluate_statistical_baselines,
    log_loss_to_log_likelihood,
)


@pytest.fixture
def synthetic_event_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    np.random.seed(42)
    n_train = 500
    n_test = 200

    times_train = pd.date_range("2026-01-01 00:00:00", periods=n_train, freq="1min", tz="UTC")
    times_test = pd.date_range("2026-01-01 08:20:00", periods=n_test, freq="1min", tz="UTC")

    def make_frame(times: pd.DatetimeIndex) -> pd.DataFrame:
        n = len(times)
        hours = times.hour.to_numpy()
        dows = times.dayofweek.to_numpy()
        ret5 = np.random.normal(0, 0.001, n)
        prev_ret5 = np.roll(ret5, 1)
        bar_ret5 = np.random.normal(0, 0.002, n)
        bar_ret15 = np.random.normal(0, 0.003, n)
        spread = np.random.uniform(0.1, 0.3, n)
        vol = np.abs(np.random.normal(0.002, 0.001, n))
        intensity = np.random.poisson(10, n).astype(float)

        # Signal: higher probability at hour 14 or when ret5 > 0.0015
        p = 0.02 + 0.1 * (hours == 14).astype(float) + 0.15 * (ret5 > 0.0015).astype(float)
        targets = (np.random.rand(n) < p).astype(int)

        return pd.DataFrame({
            "decision_time_utc": times,
            "hour_utc": hours,
            "day_of_week": dows,
            "is_ny_session": ((hours >= 13) & (hours <= 20)).astype(int),
            "is_london_session": ((hours >= 8) & (hours <= 16)).astype(int),
            "ret5": ret5,
            "prev_ret5": prev_ret5,
            "bar_ret5": bar_ret5,
            "bar_ret15": bar_ret15,
            "bar_volatility": vol,
            "bar_range": vol * 1.5,
            "bar_hl_ratio": 1.0,
            "spread": spread,
            "volatility": vol,
            "tick_intensity": intensity,
            "is_trade_entry": targets,
        })

    train_df = make_frame(times_train)
    test_df = make_frame(times_test)
    return train_df, test_df


def test_bits_per_event_calculation() -> None:
    # If candidate LL is higher than baseline, bits per event is positive
    bpe = calculate_bits_per_event(log_lik_candidate=-100.0, log_lik_baseline=-150.0, num_events=50)
    assert bpe > 0.0
    # Expected: (50) / (50 * ln(2)) = 1 / ln(2) = ~1.442695
    assert np.isclose(bpe, 1.0 / np.log(2.0), rtol=1e-4)

    # Edge cases
    assert calculate_bits_per_event(-100.0, -100.0, 50) == 0.0
    assert calculate_bits_per_event(-100.0, -150.0, 0) == 0.0


def test_log_loss_to_log_likelihood() -> None:
    probs = np.array([0.9, 0.1, 0.8])
    targets = np.array([1, 0, 1])
    ll = log_loss_to_log_likelihood(probs, targets)
    expected = np.log(0.9) + np.log(0.9) + np.log(0.8)
    assert np.isclose(ll, expected)


def test_b0_homogeneous_poisson_fit_predict(synthetic_event_data) -> None:
    train_df, test_df = synthetic_event_data
    model = B0HomogeneousPoissonModel()
    model.fit(train_df, "is_trade_entry")

    assert model.num_samples_ == len(train_df)
    assert model.num_events_ == int(train_df["is_trade_entry"].sum())

    probs = model.predict_proba(test_df)
    assert len(probs) == len(test_df)
    assert np.all(probs == model.baseline_prob_)

    ll = model.log_likelihood(test_df, "is_trade_entry")
    assert np.isfinite(ll)
    assert ll < 0.0


def test_feature_intensity_models_fit_predict(synthetic_event_data) -> None:
    train_df, test_df = synthetic_event_data

    models = [
        B1DiurnalCalendarModel(),
        B2CompletedBarModel(),
        B3CausalTickModel(),
        B4JointBarTickModel(),
    ]

    for m in models:
        m.fit(train_df, "is_trade_entry")
        assert m.is_fitted_ is True

        p_train = m.predict_proba(train_df)
        p_test = m.predict_proba(test_df)

        assert len(p_train) == len(train_df)
        assert len(p_test) == len(test_df)
        assert np.all((p_train >= 0.0) & (p_train <= 1.0))
        assert np.all((p_test >= 0.0) & (p_test <= 1.0))

        ll_train = m.log_likelihood(train_df, "is_trade_entry")
        ll_test = m.log_likelihood(test_df, "is_trade_entry")
        assert np.isfinite(ll_train)
        assert np.isfinite(ll_test)


def test_b5_hawkes_self_exciting_model(synthetic_event_data) -> None:
    train_df, test_df = synthetic_event_data
    model = B5HawkesSelfExcitingModel()
    model.fit(train_df, "is_trade_entry")

    assert model.is_fitted_ is True
    assert model.alpha >= 0.0
    assert model.beta > 0.0

    p_test = model.predict_proba(test_df)
    assert len(p_test) == len(test_df)
    assert np.all((p_test >= 0.0) & (p_test <= 1.0))

    ll = model.log_likelihood(test_df, "is_trade_entry")
    assert np.isfinite(ll)


def test_evaluate_statistical_baselines_suite(synthetic_event_data) -> None:
    train_df, test_df = synthetic_event_data
    summary_df, fitted_models = evaluate_statistical_baselines(train_df, test_df, "is_trade_entry")

    assert len(summary_df) == 6
    assert len(fitted_models) == 6
    assert "model_name" in summary_df.columns
    assert "test_bits_per_event" in summary_df.columns
    assert "train_log_likelihood" in summary_df.columns
    assert "test_log_likelihood" in summary_df.columns

    # Check that all models have finite likelihoods
    assert np.all(np.isfinite(summary_df["train_log_likelihood"]))
    assert np.all(np.isfinite(summary_df["test_log_likelihood"]))
