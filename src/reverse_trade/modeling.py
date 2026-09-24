"""Optional market-state diagnostics and candidate-signal reproduction scoring.

These functions require synchronized market features and are not called for the
trade-only run.  They enforce chronological validation and keep score
components separate instead of hiding them in an arbitrary weighted total.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


@dataclass(frozen=True)
class MatchTolerances:
    entry_seconds: float = 120.0
    price_units: float | None = None
    exit_seconds: float = 180.0
    size_units: float = 1e-9


def build_decision_panel(
    market_features: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    timestamp_column: str = "timestamp",
    tolerance: pd.Timedelta = pd.Timedelta("2min"),
) -> pd.DataFrame:
    """Label eligible market rows as Sell=-1, NoTrade=0, Buy=1.

    The caller must first establish that every market row was genuinely an
    opportunity.  This function does not infer trading hours or broker outages.
    """

    panel = market_features.sort_values(timestamp_column).copy()
    panel["decision"] = 0
    panel["matched_ticket"] = ""
    times = panel[timestamp_column].to_numpy(dtype="datetime64[ns]")
    for trade in trades.sort_values("open_time").itertuples(index=False):
        target = np.datetime64(trade.open_time)
        insertion = int(np.searchsorted(times, target))
        candidates = [index for index in [insertion - 1, insertion] if 0 <= index < len(panel)]
        if not candidates:
            continue
        best = min(candidates, key=lambda index: abs(times[index] - target))
        lag = abs(pd.Timestamp(times[best]) - trade.open_time)
        if lag <= tolerance:
            panel.iloc[best, panel.columns.get_loc("decision")] = 1 if trade.side == "Buy" else -1
            panel.iloc[best, panel.columns.get_loc("matched_ticket")] = trade.ticket
    return panel


def expanding_time_folds(n_rows: int, *, minimum_train: int, test_size: int) -> list[tuple[np.ndarray, np.ndarray]]:
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    train_end = minimum_train
    while train_end + test_size <= n_rows:
        folds.append((np.arange(train_end), np.arange(train_end, train_end + test_size)))
        train_end += test_size
    return folds


def _make_preprocessor(frame: pd.DataFrame, feature_columns: list[str]) -> ColumnTransformer:
    categorical = [column for column in feature_columns if not pd.api.types.is_numeric_dtype(frame[column])]
    numeric = [column for column in feature_columns if column not in categorical]
    return ColumnTransformer(
        [
            (
                "numeric",
                Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]),
                numeric,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ]
    )


def time_aware_classifier_diagnostics(
    panel: pd.DataFrame,
    feature_columns: list[str],
    *,
    minimum_train: int,
    test_size: int,
    seed: int = 20260919,
) -> pd.DataFrame:
    """Evaluate diagnostic classifiers on expanding chronological folds."""

    models = {
        "multinomial_logistic": LogisticRegression(max_iter=2_000, class_weight="balanced", random_state=seed),
        "random_forest": RandomForestClassifier(
            n_estimators=500, min_samples_leaf=10, class_weight="balanced_subsample", random_state=seed
        ),
        "gradient_boosting": GradientBoostingClassifier(random_state=seed),
    }
    rows: list[dict[str, object]] = []
    for fold_number, (train_index, test_index) in enumerate(
        expanding_time_folds(len(panel), minimum_train=minimum_train, test_size=test_size), start=1
    ):
        train = panel.iloc[train_index]
        test = panel.iloc[test_index]
        for name, estimator in models.items():
            pipeline = Pipeline([("features", _make_preprocessor(train, feature_columns)), ("model", estimator)])
            pipeline.fit(train[feature_columns], train["decision"])
            predicted = pipeline.predict(test[feature_columns])
            probabilities = pipeline.predict_proba(test[feature_columns])
            labels = pipeline.named_steps["model"].classes_
            rows.append(
                {
                    "fold": fold_number,
                    "model": name,
                    "train_end": train.index[-1],
                    "test_start": test.index[0],
                    "test_end": test.index[-1],
                    "balanced_accuracy": balanced_accuracy_score(test["decision"], predicted),
                    "log_loss": log_loss(test["decision"], probabilities, labels=labels),
                    "confusion_matrix": confusion_matrix(test["decision"], predicted, labels=[-1, 0, 1]).tolist(),
                }
            )
    return pd.DataFrame(rows)


def score_reproduction(
    observed: pd.DataFrame,
    generated: pd.DataFrame,
    tolerances: MatchTolerances = MatchTolerances(),
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Greedily match generated trades to observed trades and report components."""

    remaining = set(generated.index)
    matches: list[dict[str, object]] = []
    for trade in observed.sort_values("open_time").itertuples():
        candidates = generated.loc[list(remaining)] if remaining else generated.iloc[0:0]
        if candidates.empty:
            matches.append({"observed_ticket": trade.ticket, "matched": False})
            continue
        entry_error = (candidates["open_time"] - trade.open_time).abs().dt.total_seconds()
        candidates = candidates[entry_error <= tolerances.entry_seconds]
        if candidates.empty:
            matches.append({"observed_ticket": trade.ticket, "matched": False})
            continue
        chosen_index = (candidates["open_time"] - trade.open_time).abs().idxmin()
        generated_trade = generated.loc[chosen_index]
        remaining.remove(chosen_index)
        entry_error_seconds = abs((generated_trade["open_time"] - trade.open_time).total_seconds())
        exit_error_seconds = abs((generated_trade["close_time"] - trade.close_time).total_seconds())
        price_error = abs(generated_trade["observed_price"] - trade.observed_price)
        matches.append(
            {
                "observed_ticket": trade.ticket,
                "generated_index": chosen_index,
                "matched": True,
                "direction_match": generated_trade["side"] == trade.side,
                "entry_error_seconds": entry_error_seconds,
                "entry_within_tolerance": entry_error_seconds <= tolerances.entry_seconds,
                "exit_error_seconds": exit_error_seconds,
                "exit_within_tolerance": exit_error_seconds <= tolerances.exit_seconds,
                "price_error": price_error,
                "price_within_tolerance": tolerances.price_units is None or price_error <= tolerances.price_units,
                "size_error": abs(generated_trade["lot_size"] - trade.lot_size),
                "size_match": abs(generated_trade["lot_size"] - trade.lot_size) <= tolerances.size_units,
            }
        )
    match_table = pd.DataFrame(matches)
    matched = match_table[match_table["matched"]]
    components = {
        "observed_trade_match_rate": float(match_table["matched"].mean()),
        "generated_precision": float(len(matched) / len(generated)) if len(generated) else 0.0,
        "direction_match_rate": float(matched["direction_match"].mean()) if len(matched) else 0.0,
        "entry_tolerance_match_rate": float(matched["entry_within_tolerance"].mean()) if len(matched) else 0.0,
        "exit_tolerance_match_rate": float(matched["exit_within_tolerance"].mean()) if len(matched) else 0.0,
        "price_tolerance_match_rate": float(matched["price_within_tolerance"].mean()) if len(matched) else 0.0,
        "size_match_rate": float(matched["size_match"].mean()) if len(matched) else 0.0,
    }
    return match_table, components

