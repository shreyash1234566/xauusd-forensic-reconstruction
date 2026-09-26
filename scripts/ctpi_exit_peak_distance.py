"""Terminal CTPI diagnostic: peak-distance-indexed exit hazard.

The primary model replaces holding-age terms with a nonlinear spline of
drawdown from the running MFE. A piecewise-exponential counting-process
likelihood uses the exact exposure of every risk interval. The already-opened
lockbox makes this a terminal prespecified diagnostic, not independent
confirmation.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ctpi_exit_investigation import (
    BASE_FEATURES,
    EXPECTED_LEDGER_SHA256,
    LEDGER,
    LOCKBOX_START,
    SEED,
    sign_flip_pvalue,
)


PANEL = ROOT / "outputs" / "ctpi_exit_investigation" / "exit_risk_panel.parquet"
OUTPUT = ROOT / "outputs" / "ctpi_exit_peak_distance"

AGE_FEATURES = BASE_FEATURES
CALENDAR_FEATURES = [
    "side_buy",
    "tod_sin_1",
    "tod_cos_1",
    "tod_sin_2",
    "tod_cos_2",
    "tod_sin_3",
    "tod_cos_3",
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
]
ALPHAS = (1e-6, 1e-4, 1e-3, 1e-2, 1e-1, 1.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def add_exact_exposure(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.sort_values(["ticket", "age_seconds"]).reset_index(drop=True).copy()
    previous_age = panel.groupby("ticket", sort=False).age_seconds.shift(fill_value=0.0)
    panel["exposure_seconds"] = panel.age_seconds - previous_age
    if (panel.exposure_seconds <= 0).any():
        raise ValueError("Risk intervals must have strictly positive exposure")
    if not (panel.groupby("ticket").event.sum() == 1).all():
        raise ValueError("Every included trade must contribute exactly one exit event")
    return panel


def make_pipeline(specification: str, alpha: float) -> Pipeline:
    if specification == "age_calendar":
        transform = ColumnTransformer([("age_calendar", StandardScaler(), AGE_FEATURES)])
    elif specification == "peak_distance_calendar":
        peak = Pipeline(
            [
                ("spline", SplineTransformer(n_knots=5, degree=2, knots="quantile", include_bias=False)),
                ("scale", StandardScaler()),
            ]
        )
        transform = ColumnTransformer(
            [
                ("calendar", StandardScaler(), CALENDAR_FEATURES),
                ("peak_distance", peak, ["drawdown_from_mfe"]),
            ]
        )
    elif specification == "age_plus_peak_distance":
        peak = Pipeline(
            [
                ("spline", SplineTransformer(n_knots=5, degree=2, knots="quantile", include_bias=False)),
                ("scale", StandardScaler()),
            ]
        )
        transform = ColumnTransformer(
            [
                ("age_calendar", StandardScaler(), AGE_FEATURES),
                ("peak_distance", peak, ["drawdown_from_mfe"]),
            ]
        )
    else:
        raise ValueError(f"Unknown specification: {specification}")
    return Pipeline(
        [
            ("features", transform),
            ("hazard", PoissonRegressor(alpha=alpha, fit_intercept=True, max_iter=3000, tol=1e-10)),
        ]
    )


def counting_process_ll(frame: pd.DataFrame, hazard_per_second: np.ndarray) -> float:
    hazard = np.clip(np.asarray(hazard_per_second, dtype=float), 1e-12, 1e6)
    events = frame.event.to_numpy(float)
    exposure = frame.exposure_seconds.to_numpy(float)
    return float(np.sum(events * np.log(hazard) - hazard * exposure))


def fit_frozen_model(
    train: pd.DataFrame, validation: pd.DataFrame, specification: str
) -> tuple[Pipeline, float, list[dict]]:
    selection = []
    best = None
    for alpha in ALPHAS:
        model = make_pipeline(specification, alpha)
        target_rate = train.event.to_numpy(float) / train.exposure_seconds.to_numpy(float)
        model.fit(
            train,
            target_rate,
            hazard__sample_weight=train.exposure_seconds.to_numpy(float),
        )
        ll = counting_process_ll(validation, model.predict(validation))
        selection.append({"alpha": alpha, "validation_counting_process_log_likelihood": ll})
        if best is None or ll > best[0]:
            best = (ll, alpha)
    assert best is not None
    selected_alpha = float(best[1])
    discovery = pd.concat([train, validation], ignore_index=True)
    frozen = make_pipeline(specification, selected_alpha)
    target_rate = discovery.event.to_numpy(float) / discovery.exposure_seconds.to_numpy(float)
    frozen.fit(
        discovery,
        target_rate,
        hazard__sample_weight=discovery.exposure_seconds.to_numpy(float),
    )
    return frozen, selected_alpha, selection


def per_trade_ll(frame: pd.DataFrame, hazard_per_second: np.ndarray) -> pd.Series:
    hazard = np.clip(np.asarray(hazard_per_second, dtype=float), 1e-12, 1e6)
    contribution = frame.event.to_numpy(float) * np.log(hazard) - hazard * frame.exposure_seconds.to_numpy(float)
    return pd.Series(contribution).groupby(frame.ticket.reset_index(drop=True)).sum()


def time_rescaling(frame: pd.DataFrame, hazard_per_second: np.ndarray) -> dict:
    work = frame[["ticket", "exposure_seconds"]].copy()
    work["integrated_hazard"] = np.clip(hazard_per_second, 1e-12, 1e6) * work.exposure_seconds
    cumulative = work.groupby("ticket").integrated_hazard.sum().to_numpy()
    transformed = 1 - np.exp(-cumulative)
    statistic, pvalue = stats.kstest(transformed, "uniform")
    return {
        "n_trades": int(len(transformed)),
        "ks_statistic": float(statistic),
        "ks_pvalue": float(pvalue),
        "mean_transformed": float(np.mean(transformed)),
        "gate": "PASS" if pvalue >= 0.05 else "FAIL",
    }


def render_report(result: dict, table: pd.DataFrame) -> str:
    primary = table.loc[table.specification == "peak_distance_calendar"].iloc[0]
    return f"""# CTPI terminal peak-distance exit diagnostic

## Decision

{result['decision']}

This is a terminal prespecified diagnostic on the previously opened chronological
lockbox. It is not an independent confirmation test.

## Frozen acceptance rule

The primary `peak_distance_calendar` model passes only when its lockbox
time-rescaling KS p-value is at least 0.05. Failure freezes exit reconstruction
on this ledger. No further exit features are authorized by this diagnostic.

## Model

The hazard is piecewise exponential. Each risk interval contributes its exact
exposure in seconds. The primary hazard replaces holding-age terms with a
five-knot quadratic spline of `drawdown_from_mfe = MFE - unrealized_move`, while
retaining side and calendar controls. Hyperparameter selection uses discovery
data only.

| specification | bits/exit vs age model | sign-flip p | KS p | calibration |
| --- | ---: | ---: | ---: | --- |
{chr(10).join(f"| {r.specification} | {r.incremental_bits_per_exit_vs_age:.4f} | {r.sign_flip_pvalue_vs_age:.4g} | {r.ks_pvalue:.4g} | {r.calibration_gate} |" for r in table.itertuples(index=False))}

The primary peak-distance result is {primary.incremental_bits_per_exit_vs_age:.4f}
bits per exit relative to the exposure-corrected age/calendar model, with KS
p={primary.ks_pvalue:.6g}.

## Interpretation

Passing calibration would show that peak-relative distance is an adequate state
coordinate for the observed exit-time distribution; it would not identify a
unique deterministic stop or original source code. Failing calibration rejects
this final motivated reparameterization under the available public-tick
observation model.
"""


def main() -> None:
    if sha256(LEDGER) != EXPECTED_LEDGER_SHA256:
        raise RuntimeError("Canonical ledger hash mismatch")
    panel = add_exact_exposure(pd.read_parquet(PANEL))
    discovery = panel[panel.open_time_utc < LOCKBOX_START].copy()
    lockbox = panel[panel.open_time_utc >= LOCKBOX_START].copy()
    tickets = discovery[["ticket", "open_time_utc"]].drop_duplicates().sort_values("open_time_utc")
    inner_cut = tickets.open_time_utc.quantile(0.75)
    train = discovery[discovery.open_time_utc < inner_cut]
    validation = discovery[discovery.open_time_utc >= inner_cut]

    specifications = ("age_calendar", "peak_distance_calendar", "age_plus_peak_distance")
    fitted = {}
    for specification in specifications:
        model, alpha, selection = fit_frozen_model(train, validation, specification)
        hazard = model.predict(lockbox)
        fitted[specification] = {
            "model": model,
            "hazard": hazard,
            "selected_alpha": alpha,
            "selection": selection,
            "ll": counting_process_ll(lockbox, hazard),
            "trade_ll": per_trade_ll(lockbox, hazard),
            "rescaling": time_rescaling(lockbox, hazard),
        }

    age = fitted["age_calendar"]
    rows = []
    for index, specification in enumerate(specifications):
        item = fitted[specification]
        common = age["trade_ll"].index.intersection(item["trade_ll"].index)
        delta = (item["trade_ll"].loc[common] - age["trade_ll"].loc[common]).to_numpy()
        rows.append(
            {
                "specification": specification,
                "selected_alpha": item["selected_alpha"],
                "lockbox_counting_process_log_likelihood": item["ll"],
                "incremental_bits_per_exit_vs_age": (item["ll"] - age["ll"])
                / (math.log(2) * lockbox.event.sum()),
                "sign_flip_pvalue_vs_age": 1.0
                if specification == "age_calendar"
                else sign_flip_pvalue(delta, seed=SEED + 100 + index),
                "ks_statistic": item["rescaling"]["ks_statistic"],
                "ks_pvalue": item["rescaling"]["ks_pvalue"],
                "mean_rescaled_event_time": item["rescaling"]["mean_transformed"],
                "calibration_gate": item["rescaling"]["gate"],
            }
        )
    table = pd.DataFrame(rows)
    primary = table.loc[table.specification == "peak_distance_calendar"].iloc[0]
    passed = bool(primary.calibration_gate == "PASS")
    taxonomy = "PEAK_DISTANCE_BASELINE_PASSES_TERMINAL_DIAGNOSTIC" if passed else "EXIT_FROZEN_AFTER_PEAK_DISTANCE_FAILURE"
    decision = (
        "Peak-distance hazard passes the declared absolute calibration gate; only discovery-frozen sequential replay is warranted."
        if passed
        else "Peak-distance hazard fails the declared absolute calibration gate. Freeze exit reconstruction on this ledger."
    )
    result = {
        "status": "complete",
        "taxonomy": taxonomy,
        "decision": decision,
        "primary_specification": "peak_distance_calendar",
        "acceptance_rule_frozen_before_execution": "lockbox time-rescaling KS p >= 0.05",
        "lockbox_reuse_warning": "The chronological lockbox was opened by the prior exit analysis; this is a terminal diagnostic, not independent confirmation.",
        "canonical_hashes": {
            "data/raw/trades_raw.tsv": sha256(LEDGER),
            "outputs/ctpi_exit_investigation/exit_risk_panel.parquet": sha256(PANEL),
        },
        "design": {
            "estimator": "piecewise-exponential Poisson counting-process hazard",
            "exact_interval_exposure": True,
            "discovery_trades": int(discovery.ticket.nunique()),
            "lockbox_trades": int(lockbox.ticket.nunique()),
            "inner_discovery_cut_utc": inner_cut.isoformat(),
            "primary_state_variable": "drawdown_from_mfe = MFE - unrealized_move",
            "primary_functional_form": "five-knot quadratic quantile spline",
        },
        "models": {
            name: {
                "selected_alpha": item["selected_alpha"],
                "regularization_selection": item["selection"],
                "lockbox_log_likelihood": item["ll"],
                "time_rescaling": item["rescaling"],
            }
            for name, item in fitted.items()
        },
        "primary_passed": passed,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT / "peak_distance_model_comparison.csv", index=False)
    (OUTPUT / "peak_distance_verdict.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUTPUT / "CTPI_PEAK_DISTANCE_REPORT.md").write_text(render_report(result, table), encoding="utf-8")
    print(json.dumps({"taxonomy": taxonomy, "primary": table.iloc[1].to_dict()}, indent=2))


if __name__ == "__main__":
    main()
