"""Phase 13: frozen clock intensity and offset-conditioned market tests.

The clock model is learned only from every observed M1 opportunity in the
discovery interval.  Each market feature is then fitted alone on the fixed
discovery strata with the clock linear predictor as an offset, and evaluated
once on the existing 102-epoch lockbox.  No lockbox coefficient, scale, clock
parameter, or feature selection is fitted.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from sklearn.linear_model import PoissonRegressor


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "strategy_reconstruction" / "phase13_clock_offset"
PANEL = ROOT / "data" / "processed" / "decision_panel.parquet"
EPOCH_MAP = ROOT / "outputs" / "strategy_reconstruction" / "phase10_11_decision_epoch_map.csv"
DISCOVERY = ROOT / "outputs" / "strategy_reconstruction" / "phase10_11_features.parquet"
LOCKBOX = ROOT / "outputs" / "strategy_reconstruction" / "phase10_11_lockbox_scores.parquet"
LEDGER = ROOT / "data" / "raw" / "trades_raw.tsv"
RECON = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

SEED = 20260925
HARMONICS = 6
ALPHAS = (0.0, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0)
PERMUTATIONS = 9999
MARKET_FEATURES = (
    "jump_z", "disp30", "tick_rate_ratio", "spread_now",
    "spread_ratio", "ret5", "n_ticks_300",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def clock_design(hour: Iterable[float], minute: Iterable[float], dow: Iterable[float]) -> tuple[np.ndarray, list[str]]:
    hour_arr = np.asarray(hour, dtype=float)
    minute_arr = np.asarray(minute, dtype=float)
    dow_arr = np.asarray(dow, dtype=int)
    phase = 2.0 * np.pi * (hour_arr * 60.0 + minute_arr) / 1440.0
    columns: list[np.ndarray] = []
    names: list[str] = []
    for k in range(1, HARMONICS + 1):
        columns.extend((np.sin(k * phase), np.cos(k * phase)))
        names.extend((f"tod_sin_{k}", f"tod_cos_{k}"))
    for day in range(1, 7):
        columns.append((dow_arr == day).astype(float))
        names.append(f"dow_{day}")
    return np.column_stack(columns), names


def poisson_log_likelihood(y: np.ndarray, eta: np.ndarray) -> float:
    return float(np.sum(y * eta - np.exp(np.clip(eta, -30.0, 10.0))))


def conditional_log_likelihood(frame: pd.DataFrame, offset: np.ndarray, beta: float, z: np.ndarray) -> tuple[float, np.ndarray]:
    work = frame[["group", "y"]].copy()
    work["offset"] = offset
    work["z"] = z
    contributions: list[float] = []
    for _, group in work.groupby("group", sort=False):
        y = group.y.to_numpy(int)
        if y.sum() != 1:
            raise ValueError("Each conditional stratum must contain exactly one case")
        eta = group.offset.to_numpy(float) + beta * group.z.to_numpy(float)
        contributions.append(float(eta[np.flatnonzero(y)[0]] - logsumexp(eta)))
    values = np.asarray(contributions)
    return float(values.sum()), values


def fit_single_feature(frame: pd.DataFrame, offset: np.ndarray, z: np.ndarray) -> float:
    objective = lambda beta: -conditional_log_likelihood(frame, offset, float(beta), z)[0]
    result = minimize_scalar(objective, bounds=(-8.0, 8.0), method="bounded", options={"xatol": 1e-10})
    if not result.success:
        raise RuntimeError(f"Feature coefficient fit failed: {result.message}")
    return float(result.x)


def _conditional_delta(frame: pd.DataFrame, offset: np.ndarray, beta: float, z: np.ndarray) -> tuple[float, np.ndarray]:
    candidate, candidate_parts = conditional_log_likelihood(frame, offset, beta, z)
    base, base_parts = conditional_log_likelihood(frame, offset, 0.0, z)
    return candidate - base, candidate_parts - base_parts


def conditional_randomization_pvalue(
    frame: pd.DataFrame,
    offset: np.ndarray,
    beta: float,
    z: np.ndarray,
    *,
    permutations: int = PERMUTATIONS,
    seed: int = SEED,
) -> float:
    rng = np.random.default_rng(seed)
    observed, _ = _conditional_delta(frame, offset, beta, z)
    simulated = np.zeros(permutations, dtype=float)
    work = frame[["group", "y"]].copy()
    work["offset"] = offset
    work["z"] = z
    for _, group in work.groupby("group", sort=False):
        off = group.offset.to_numpy(float)
        cand = off + beta * group.z.to_numpy(float)
        p = np.exp(off - logsumexp(off))
        delta_by_index = (cand - logsumexp(cand)) - (off - logsumexp(off))
        chosen = rng.choice(len(group), size=permutations, replace=True, p=p)
        simulated += delta_by_index[chosen]
    return float((1 + np.count_nonzero(simulated >= observed - 1e-12)) / (permutations + 1))


def uniform_clock_pvalue(frame: pd.DataFrame, offset: np.ndarray, *, permutations: int = PERMUTATIONS) -> tuple[float, float]:
    rng = np.random.default_rng(SEED + 17)
    observed = 0.0
    simulated = np.zeros(permutations, dtype=float)
    work = frame[["group", "y"]].copy()
    work["offset"] = offset
    for _, group in work.groupby("group", sort=False):
        off = group.offset.to_numpy(float)
        y = group.y.to_numpy(int)
        case = int(np.flatnonzero(y)[0])
        delta = off - logsumexp(off) + math.log(len(group))
        observed += float(delta[case])
        simulated += delta[rng.integers(0, len(group), size=permutations)]
    pvalue = float((1 + np.count_nonzero(simulated >= observed - 1e-12)) / (permutations + 1))
    return observed, pvalue


def holm_adjust(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = np.empty(len(pvalues), dtype=float)
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (len(pvalues) - rank) * pvalues[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted.tolist()


def _load_partitions() -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    mapping = pd.read_csv(EPOCH_MAP)
    mapping["decision_time_utc"] = pd.to_datetime(mapping.decision_time_utc, utc=True, format="mixed")
    discovery = mapping.loc[mapping.record_partition.eq("discovery"), "decision_time_utc"]
    lockbox = mapping.loc[mapping.record_partition.eq("lockbox"), "decision_time_utc"]
    return discovery.min(), discovery.max(), lockbox.min(), lockbox.max()


def _exposure_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    d0, d1, l0, l1 = _load_partitions()
    panel = pd.read_parquet(PANEL, columns=["dt", "is_trade"])
    panel["dt"] = pd.to_datetime(panel.dt, utc=True)
    panel["hour"] = panel.dt.dt.hour
    panel["minute"] = panel.dt.dt.minute
    panel["dow"] = panel.dt.dt.dayofweek
    discovery = panel.loc[panel.dt.between(d0.floor("min"), d1.floor("min"), inclusive="both")].copy()
    lockbox = panel.loc[panel.dt.between(l0.floor("min"), l1.floor("min"), inclusive="both")].copy()
    return discovery, lockbox


def _fit_clock(discovery: pd.DataFrame, lockbox: pd.DataFrame) -> tuple[PoissonRegressor, dict]:
    X, names = clock_design(discovery.hour, discovery.minute, discovery.dow)
    y = discovery.is_trade.to_numpy(float)
    unique_days = np.sort(discovery.dt.dt.floor("D").unique())
    split_day = unique_days[int(len(unique_days) * 0.75)]
    train = discovery.dt.dt.floor("D") < split_day
    scores = []
    for alpha in ALPHAS:
        model = PoissonRegressor(alpha=alpha, max_iter=4000, tol=1e-10)
        model.fit(X[train], y[train])
        eta = model.intercept_ + X[~train] @ model.coef_
        score = poisson_log_likelihood(y[~train], eta)
        scores.append({"alpha": alpha, "validation_log_likelihood": score})
    best_alpha = max(scores, key=lambda row: row["validation_log_likelihood"])["alpha"]
    model = PoissonRegressor(alpha=best_alpha, max_iter=4000, tol=1e-10)
    model.fit(X, y)
    X_lock, _ = clock_design(lockbox.hour, lockbox.minute, lockbox.dow)
    eta_lock = model.intercept_ + X_lock @ model.coef_
    baseline_eta = np.full(len(lockbox), math.log((y.sum() + 0.5) / (len(y) + 1.0)))
    gain = poisson_log_likelihood(lockbox.is_trade.to_numpy(float), eta_lock) - poisson_log_likelihood(lockbox.is_trade.to_numpy(float), baseline_eta)
    events = int(lockbox.is_trade.sum())
    summary = {
        "design": names, "harmonics": HARMONICS, "selected_alpha": best_alpha,
        "alpha_selection": scores, "intercept": float(model.intercept_),
        "coefficients": {name: float(value) for name, value in zip(names, model.coef_)},
        "discovery_minutes": len(discovery), "discovery_events": int(y.sum()),
        "lockbox_minutes": len(lockbox), "lockbox_events": events,
        "full_exposure_lockbox_bits_per_event_vs_constant": float(gain / (max(events, 1) * math.log(2.0))),
        "fit_scope": "discovery only; every observed M1 minute across the full 24-hour market panel",
    }
    return model, summary


def _clock_offset_from_frame(model: PoissonRegressor, frame: pd.DataFrame) -> np.ndarray:
    X, _ = clock_design(frame.hour, frame.minute, frame.dow)
    return model.intercept_ + X @ model.coef_


def _discovery_strata() -> pd.DataFrame:
    frame = pd.read_parquet(DISCOVERY, columns=[*MARKET_FEATURES, "utc_hour", "utc_minute", "day_of_week", "y", "groups"])
    frame = frame.rename(columns={"groups": "group", "utc_hour": "hour", "utc_minute": "minute", "day_of_week": "dow"})
    case_hours = frame.loc[frame.y.eq(1)].set_index("group").hour
    supported = case_hours.loc[case_hours.between(5, 16)].index
    return frame.loc[frame.group.isin(supported)].copy()


def _lockbox_strata() -> pd.DataFrame:
    raw_columns = [f"feat_raw_{feature}" for feature in MARKET_FEATURES]
    frame = pd.read_parquet(LOCKBOX, columns=["epoch_id", "is_case", "timestamp_utc", *raw_columns])
    frame["timestamp_utc"] = pd.to_datetime(frame.timestamp_utc, utc=True, format="mixed")
    frame["hour"] = frame.timestamp_utc.dt.hour.astype(float)
    frame["minute"] = frame.timestamp_utc.dt.minute.astype(float)
    frame["dow"] = frame.timestamp_utc.dt.dayofweek.astype(float)
    frame["group"] = frame.epoch_id
    frame["y"] = frame.is_case.astype(int)
    frame = frame.rename(columns={f"feat_raw_{feature}": feature for feature in MARKET_FEATURES})
    case_hours = frame.loc[frame.y.eq(1)].set_index("group").hour
    supported = case_hours.loc[case_hours.between(5, 16)].index
    return frame.loc[frame.group.isin(supported)].copy()


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    discovery_exposure, lockbox_exposure = _exposure_panel()
    clock_model, clock_summary = _fit_clock(discovery_exposure, lockbox_exposure)
    discovery = _discovery_strata()
    lockbox = _lockbox_strata()
    discovery_offset = _clock_offset_from_frame(clock_model, discovery)
    lockbox_offset = _clock_offset_from_frame(clock_model, lockbox)

    discovery_clock_delta, _ = uniform_clock_pvalue(discovery, discovery_offset, permutations=999)
    lockbox_clock_delta, lockbox_clock_p = uniform_clock_pvalue(lockbox, lockbox_offset)
    clock_summary.update({
        "discovery_conditional_bits_per_event_vs_uniform": discovery_clock_delta / (discovery.group.nunique() * math.log(2.0)),
        "lockbox_conditional_bits_per_event_vs_uniform": lockbox_clock_delta / (lockbox.group.nunique() * math.log(2.0)),
        "lockbox_conditional_randomization_pvalue": lockbox_clock_p,
        "discovery_supported_risk_set_strata": int(discovery.group.nunique()),
        "lockbox_supported_risk_set_strata": int(lockbox.group.nunique()),
        "risk_set_positivity_rule": "Market tests retain only legacy broad strata whose case UTC hour is within the control support 05:00-16:59.",
    })
    clock_freeze = {
        **clock_summary,
        "input_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in (PANEL, EPOCH_MAP, LEDGER, RECON)},
        "lockbox_used_for_fitting": False,
    }
    freeze_payload = json.dumps(clock_freeze, sort_keys=True).encode()
    clock_freeze["freeze_hash"] = hashlib.sha256(freeze_payload).hexdigest().upper()
    (OUT / "clock_intensity_freeze.json").write_text(json.dumps(clock_freeze, indent=2), encoding="utf-8")

    rows = []
    raw_pvalues = []
    for feature_index, feature in enumerate(MARKET_FEATURES):
        mean = float(discovery[feature].mean())
        std = float(discovery[feature].std(ddof=0))
        if not np.isfinite(std) or std < 1e-12:
            raise ValueError(f"Degenerate discovery feature: {feature}")
        z_dev = (discovery[feature].to_numpy(float) - mean) / std
        z_lock = (lockbox[feature].to_numpy(float) - mean) / std
        beta = fit_single_feature(discovery, discovery_offset, z_dev)
        dev_delta, dev_parts = _conditional_delta(discovery, discovery_offset, beta, z_dev)
        lock_delta, lock_parts = _conditional_delta(lockbox, lockbox_offset, beta, z_lock)
        pvalue = conditional_randomization_pvalue(lockbox, lockbox_offset, beta, z_lock, seed=SEED + feature_index)
        raw_pvalues.append(pvalue)
        rows.append({
            "feature": feature, "discovery_mean": mean, "discovery_std": std, "frozen_beta": beta,
            "discovery_strata": int(discovery.group.nunique()), "lockbox_strata": int(lockbox.group.nunique()),
            "discovery_bits_per_event_vs_clock": float(dev_delta / (len(dev_parts) * math.log(2.0))),
            "lockbox_bits_per_event_vs_clock": float(lock_delta / (len(lock_parts) * math.log(2.0))),
            "lockbox_median_delta_bits": float(np.median(lock_parts / math.log(2.0))),
            "lockbox_positive_strata_fraction": float(np.mean(lock_parts > 0)),
            "lockbox_randomization_pvalue": pvalue,
        })
    adjusted = holm_adjust(raw_pvalues)
    for row, value in zip(rows, adjusted):
        row["lockbox_holm_pvalue"] = value
        row["passes_gate"] = bool(
            row["discovery_bits_per_event_vs_clock"] > 0
            and row["lockbox_bits_per_event_vs_clock"] > 0
            and value <= 0.05
        )
    results = pd.DataFrame(rows).sort_values("lockbox_bits_per_event_vs_clock", ascending=False)
    results.to_csv(OUT / "individual_market_feature_tests.csv", index=False)
    survivors = results.loc[results.passes_gate, "feature"].tolist()

    direction = {
        "status": "FROZEN_AS_USER_DIRECTED_PRIOR_CONSTRAINT",
        "constraint": "direction must be contrarian to the causal 2-20 minute pre-entry return",
        "reported_permutation_corrected_pvalue": 0.0033,
        "important_limitation": "The supplied 0.0033 result was not located as a reproducible project artifact in this run; it is preserved as user-directed prior information, not re-labelled as independently verified Phase 13 evidence.",
    }
    (OUT / "direction_constraint.json").write_text(json.dumps(direction, indent=2), encoding="utf-8")
    gate = {
        "clock_offset_required": True,
        "eligible_market_features": survivors,
        "rejected_market_features": results.loc[~results.passes_gate, "feature"].tolist(),
        "symbolic_search_status": "READY" if survivors else "BLOCKED_NO_INDIVIDUAL_FEATURE_CLEARED_CLOCK_OFFSET_LOCKBOX_GATE",
        "direction_constraint": direction["constraint"],
        "rule": "Only Holm-significant positive discovery-to-lockbox feature increments may enter a later combined or symbolic search.",
    }
    (OUT / "symbolic_search_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")

    report_rows = "\n".join(
        f"| {row.feature} | {row.frozen_beta:.4f} | {row.discovery_bits_per_event_vs_clock:.4f} | "
        f"{row.lockbox_bits_per_event_vs_clock:.4f} | {row.lockbox_randomization_pvalue:.4g} | "
        f"{row.lockbox_holm_pvalue:.4g} | {'PASS' if row.passes_gate else 'FAIL'} |"
        for row in results.itertuples(index=False)
    )
    report = f"""# Phase 13 — Frozen clock-offset market-feature tests

## Clock model

- Discovery exposure: **{clock_summary['discovery_minutes']:,} M1 minutes**, **{clock_summary['discovery_events']} entry minutes**.
- Lockbox exposure: **{clock_summary['lockbox_minutes']:,} M1 minutes**, **{clock_summary['lockbox_events']} entry minutes**.
- Selected discovery-only Poisson regularization: **{clock_summary['selected_alpha']}**.
- Full-exposure lockbox improvement over the discovery constant rate: **{clock_summary['full_exposure_lockbox_bits_per_event_vs_constant']:.4f} bits/event**.
- Conditional risk-set lockbox improvement over uniform choice: **{clock_summary['lockbox_conditional_bits_per_event_vs_uniform']:.4f} bits/event**, randomization **p={clock_summary['lockbox_conditional_randomization_pvalue']:.4g}**.

The frozen harmonic/day-of-week linear predictor is used as an offset in every test below. Market coefficients and standardization were fitted only on discovery strata.

## Individual market features

| Feature | Frozen beta | Discovery bits/event vs clock | Lockbox bits/event vs clock | Raw p | Holm p | Gate |
|---|---:|---:|---:|---:|---:|---|
{report_rows}

## Search gate

Eligible market features: **{', '.join(survivors) if survivors else 'none'}**.

Symbolic search: **{gate['symbolic_search_status']}**.

The result is conditional on the existing Phase 10/11 risk-set construction and public-feed observation model. It does not establish account uptime or unique source-code identity.
"""
    (OUT / "PHASE13_REPORT.md").write_text(report, encoding="utf-8")
    summary = {"status": "complete", "clock": clock_summary, "feature_survivors": survivors, "symbolic_search": gate["symbolic_search_status"]}
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
