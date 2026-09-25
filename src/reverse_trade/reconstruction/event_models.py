"""Statistical event-model baselines (Stage O) for trade arrival intensity.

Implements B0–B5 point-process and discrete-clock intensity models:
- B0: Homogeneous Poisson baseline (constant arrival intensity).
- B1: Diurnal / calendar hourly intensity model (hour + day of week).
- B2: Completed-bar feature terms (bar returns + bar volatility).
- B3: Causal tick features (realized volatility, tick intensity, spread).
- B4: Joint Bar + Tick multi-resolution feature model.
- B5: Hawkes self-exciting point-process formulation: lambda(t) = mu(t) + sum alpha * exp(-beta * (t - t_i)).

Includes log-likelihood scoring, bits-per-event information gain metrics,
and out-of-sample expanding-fold validation routines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


EPSILON = 1e-15


def calculate_bits_per_event(log_lik_candidate: float, log_lik_baseline: float, num_events: int) -> float:
    """Calculate the information gain in bits per event over a reference baseline.

    bits_per_event = (log_L(candidate) - log_L(baseline)) / (N_events * ln(2))
    """
    if num_events <= 0:
        return 0.0
    return float((log_lik_candidate - log_lik_baseline) / (num_events * np.log(2.0)))


def log_loss_to_log_likelihood(probabilities: np.ndarray, targets: np.ndarray) -> float:
    """Compute total Bernoulli log-likelihood from predicted probabilities and binary targets."""
    p = np.clip(probabilities, EPSILON, 1.0 - EPSILON)
    y = np.asarray(targets, dtype=float)
    ll = np.sum(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))
    return float(ll)


class B0HomogeneousPoissonModel:
    """B0: Homogeneous Poisson / stationary Bernoulli baseline."""

    def __init__(self, name: str = "B0_homogeneous_poisson") -> None:
        self.name = name
        self.family = "homogeneous_poisson"
        self.baseline_prob_: float = 1e-5
        self.num_events_: int = 0
        self.num_samples_: int = 0

    def fit(self, features: pd.DataFrame, target: np.ndarray | pd.Series | str = "is_trade_entry") -> "B0HomogeneousPoissonModel":
        y = features[target].to_numpy(dtype=float) if isinstance(target, str) else np.asarray(target, dtype=float)
        self.num_samples_ = len(y)
        self.num_events_ = int(np.sum(y))
        if self.num_samples_ > 0:
            self.baseline_prob_ = float(np.clip(self.num_events_ / self.num_samples_, EPSILON, 1.0 - EPSILON))
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        return np.full(len(features), self.baseline_prob_, dtype=float)

    def log_likelihood(self, features: pd.DataFrame, target: np.ndarray | pd.Series | str = "is_trade_entry") -> float:
        y = features[target].to_numpy(dtype=float) if isinstance(target, str) else np.asarray(target, dtype=float)
        p = self.predict_proba(features)
        return log_loss_to_log_likelihood(p, y)


class FeatureLogisticIntensityModel:
    """Discrete-time Bernoulli event-hazard model over designated features."""

    def __init__(
        self,
        features: Sequence[str],
        name: str = "feature_logistic",
        family: str = "logistic_intensity",
        c_regularization: float = 1.0,
    ) -> None:
        self.feature_names = list(features)
        self.name = name
        self.family = family
        self.c_regularization = c_regularization
        self.scaler = StandardScaler()
        self.model = LogisticRegression(C=c_regularization, max_iter=1000, solver="lbfgs")
        self.is_fitted_ = False
        self.fallback_prob_: float = 1e-5

    def _extract_matrix(self, features: pd.DataFrame) -> np.ndarray:
        missing = sorted(set(self.feature_names).difference(features.columns))
        if missing:
            raise ValueError(f"Missing required model features: {missing}")
        sub = features[self.feature_names].apply(pd.to_numeric, errors="coerce")
        matrix = sub.to_numpy(dtype=float)
        if not np.isfinite(matrix).all():
            raise ValueError("Feature model received missing or nonfinite values; unknown support must not be encoded as zero")
        return matrix

    def fit(self, features: pd.DataFrame, target: np.ndarray | pd.Series | str = "is_trade_entry") -> "FeatureLogisticIntensityModel":
        y = features[target].to_numpy(dtype=float) if isinstance(target, str) else np.asarray(target, dtype=float)
        self.fallback_prob_ = float(np.clip(np.mean(y), EPSILON, 1.0 - EPSILON)) if len(y) > 0 else 1e-5

        if len(np.unique(y)) <= 1:
            self.is_fitted_ = False
            return self

        X = self._extract_matrix(features)
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted_ = True
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        if not self.is_fitted_ or not any(f in features.columns for f in self.feature_names):
            return np.full(len(features), self.fallback_prob_, dtype=float)
        X = self._extract_matrix(features)
        X_scaled = self.scaler.transform(X)
        proba = self.model.predict_proba(X_scaled)[:, 1]
        return np.clip(proba, EPSILON, 1.0 - EPSILON)

    def log_likelihood(self, features: pd.DataFrame, target: np.ndarray | pd.Series | str = "is_trade_entry") -> float:
        y = features[target].to_numpy(dtype=float) if isinstance(target, str) else np.asarray(target, dtype=float)
        p = self.predict_proba(features)
        return log_loss_to_log_likelihood(p, y)


class B1DiurnalCalendarModel(FeatureLogisticIntensityModel):
    """B1: Diurnal / calendar hourly arrival model."""

    def __init__(self, name: str = "B1_diurnal_calendar") -> None:
        super().__init__(
            features=["hour_utc", "day_of_week", "is_ny_session", "is_london_session"],
            name=name,
            family="diurnal_calendar",
        )


class B2CompletedBarModel(FeatureLogisticIntensityModel):
    """B2: Completed bar return + bar volatility model."""

    def __init__(self, name: str = "B2_completed_bar") -> None:
        super().__init__(
            features=[
                "hour_utc", "day_of_week",
                "bar_ret5", "bar_ret15", "bar_volatility", "bar_range", "bar_hl_ratio",
            ],
            name=name,
            family="completed_bar",
        )


class B3CausalTickModel(FeatureLogisticIntensityModel):
    """B3: Causal tick-derived features (realized volatility, spread, return)."""

    def __init__(self, name: str = "B3_causal_tick") -> None:
        super().__init__(
            features=[
                "hour_utc", "day_of_week",
                "ret5", "prev_ret5", "spread", "volatility", "tick_intensity",
            ],
            name=name,
            family="causal_tick",
        )


class B4JointBarTickModel(FeatureLogisticIntensityModel):
    """B4: Joint multi-resolution Bar + Tick feature intensity model."""

    def __init__(self, name: str = "B4_joint_bar_tick") -> None:
        super().__init__(
            features=[
                "hour_utc", "day_of_week", "is_ny_session", "is_london_session",
                "bar_ret5", "bar_ret15", "bar_volatility", "bar_range",
                "ret5", "prev_ret5", "spread", "volatility", "tick_intensity",
            ],
            name=name,
            family="joint_bar_tick",
        )


class B5HawkesSelfExcitingModel:
    """B5: Discrete-time self-exciting Bernoulli hazard baseline.

    This is not a continuous-time Hawkes intensity. Given base event
    probability p0 and exponentially decayed event history r, the combined
    bin probability is 1 - (1-p0) exp(-alpha r).
    """

    def __init__(
        self,
        base_model: FeatureLogisticIntensityModel | None = None,
        alpha_init: float = 0.1,
        beta_init: float = 0.05,
        name: str = "B5_hawkes_self_exciting",
    ) -> None:
        self.name = name
        self.family = "hawkes_self_exciting"
        self.base_model = base_model or B1DiurnalCalendarModel()
        self.alpha = float(alpha_init)
        self.beta = float(beta_init)
        self.is_fitted_ = False

    @staticmethod
    def _compute_recursive_excitation(times_seconds: np.ndarray, events: np.ndarray, beta: float) -> np.ndarray:
        """Compute recursive exponential decay memory in O(M) time."""
        n = len(times_seconds)
        r = np.zeros(n, dtype=float)
        if n <= 1:
            return r
        for i in range(1, n):
            dt = times_seconds[i] - times_seconds[i - 1]
            if dt < 0:
                raise ValueError("Event model times must be sorted in ascending order")
            decay = np.exp(-beta * dt) if beta * dt < 700 else 0.0
            r[i] = decay * (r[i - 1] + (1.0 if events[i - 1] > 0.5 else 0.0))
        return r

    def fit(self, features: pd.DataFrame, target: np.ndarray | pd.Series | str = "is_trade_entry") -> "B5HawkesSelfExcitingModel":
        self.base_model.fit(features, target)
        y = features[target].to_numpy(dtype=float) if isinstance(target, str) else np.asarray(target, dtype=float)
        times = pd.to_datetime(features["decision_time_utc"], utc=True).astype("int64") / 1e9
        times_arr = np.asarray(times, dtype=float)

        base_p = self.base_model.predict_proba(features)

        # Optimize alpha and beta
        def loss_fn(params: np.ndarray) -> float:
            alpha, beta = params
            if alpha < 0 or beta <= 0.001:
                return 1e12
            rec = self._compute_recursive_excitation(times_arr, y, beta)
            p = np.clip(1.0 - (1.0 - base_p) * np.exp(-alpha * rec), EPSILON, 1.0 - EPSILON)
            return -log_loss_to_log_likelihood(p, y)

        res = minimize(loss_fn, [self.alpha, self.beta], method="Nelder-Mead", options={"maxiter": 100})
        if res.success and res.x[0] >= 0 and res.x[1] > 0:
            self.alpha = float(res.x[0])
            self.beta = float(res.x[1])
        self.is_fitted_ = True
        return self

    def predict_proba(self, features: pd.DataFrame, prior_events: np.ndarray | None = None) -> np.ndarray:
        base_p = self.base_model.predict_proba(features)
        times = pd.to_datetime(features["decision_time_utc"], utc=True).astype("int64") / 1e9
        times_arr = np.asarray(times, dtype=float)
        events = np.zeros(len(features), dtype=float) if prior_events is None else np.asarray(prior_events, dtype=float)
        rec = self._compute_recursive_excitation(times_arr, events, self.beta)
        p = 1.0 - (1.0 - base_p) * np.exp(-self.alpha * rec)
        return np.clip(p, EPSILON, 1.0 - EPSILON)

    def log_likelihood(self, features: pd.DataFrame, target: np.ndarray | pd.Series | str = "is_trade_entry") -> float:
        y = features[target].to_numpy(dtype=float) if isinstance(target, str) else np.asarray(target, dtype=float)
        p = self.predict_proba(features, prior_events=y)
        return log_loss_to_log_likelihood(p, y)


@dataclass(frozen=True)
class BaselineEvaluationSummary:
    model_name: str
    family: str
    train_log_likelihood: float
    test_log_likelihood: float
    train_bits_per_event: float
    test_bits_per_event: float
    num_train_events: int
    num_test_events: int
    parameters: Mapping[str, Any] = field(default_factory=dict)


def evaluate_statistical_baselines(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    target_column: str = "is_trade_entry",
) -> tuple[pd.DataFrame, list[Any]]:
    """Fit and compare the full B0-B5 statistical baseline suite."""

    models = [
        B0HomogeneousPoissonModel(),
        B1DiurnalCalendarModel(),
        B2CompletedBarModel(),
        B3CausalTickModel(),
        B4JointBarTickModel(),
        B5HawkesSelfExcitingModel(),
    ]

    # Fit all models on train
    for m in models:
        m.fit(train_frame, target_column)

    # Reference B0 likelihoods
    b0 = models[0]
    train_b0_ll = b0.log_likelihood(train_frame, target_column)
    test_b0_ll = b0.log_likelihood(test_frame, target_column)

    n_train_events = int(np.sum(train_frame[target_column]))
    n_test_events = int(np.sum(test_frame[target_column]))

    summaries: list[dict[str, Any]] = []
    for m in models:
        train_ll = m.log_likelihood(train_frame, target_column)
        test_ll = m.log_likelihood(test_frame, target_column)
        train_bpe = calculate_bits_per_event(train_ll, train_b0_ll, n_train_events)
        test_bpe = calculate_bits_per_event(test_ll, test_b0_ll, n_test_events)

        summaries.append({
            "model_name": m.name,
            "family": m.family,
            "train_log_likelihood": train_ll,
            "test_log_likelihood": test_ll,
            "train_bits_per_event": train_bpe,
            "test_bits_per_event": test_bpe,
            "num_train_events": n_train_events,
            "num_test_events": n_test_events,
        })

    summary_df = pd.DataFrame(summaries).sort_values("test_bits_per_event", ascending=False).reset_index(drop=True)
    return summary_df, models


# Aliases for alternative naming conventions across stages
ContinuousPoissonB0 = B0HomogeneousPoissonModel
DiurnalCalendarB1 = B1DiurnalCalendarModel
CompletedBarModelB2 = B2CompletedBarModel
CausalTickModelB3 = B3CausalTickModel
JointBarTickModelB4 = B4JointBarTickModel
HawkesSelfExcitingB5 = B5HawkesSelfExcitingModel
compute_bits_per_event = calculate_bits_per_event
