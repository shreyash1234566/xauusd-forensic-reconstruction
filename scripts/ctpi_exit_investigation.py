"""CTPI exit-state investigation on the canonical Phase 7C raw-tick alignment.

This is a bounded confirmatory analysis, not an unrestricted feature search.
It asks whether causal within-trade market state improves exit hazard beyond a
flexible holding-age, side, and calendar baseline on the frozen CTPI lockbox.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "raw" / "trades_raw.tsv"
RECON = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
TICKS = ROOT / "data" / "market" / "raw_ticks"
OUTPUT = ROOT / "outputs" / "ctpi_exit_investigation"

EXPECTED_LEDGER_SHA256 = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"
LOCKBOX_START = pd.Timestamp("2026-06-09 16:44:30", tz="UTC")
GRID_SECONDS = 15
SEED = 20260927

BASE_FEATURES = [
    "log_age",
    "age_hinge_3m",
    "age_hinge_10m",
    "age_hinge_30m",
    "age_hinge_60m",
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

MARKET_FEATURES = [
    "unrealized_move",
    "mfe",
    "mae",
    "drawdown_from_mfe",
    "momentum_30s",
    "momentum_120s",
    "volatility_120s",
    "spread",
    "tick_rate_15s",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class TickHourCache:
    """Small LRU cache so the 1.5 GB tick archive is never held in memory."""

    def __init__(self, directory: Path, max_hours: int = 24):
        self.directory = directory
        self.max_hours = max_hours
        self.cache: OrderedDict[str, tuple[np.ndarray, np.ndarray, np.ndarray] | None] = OrderedDict()

    def hour(self, timestamp: pd.Timestamp):
        key = timestamp.strftime("%Y-%m-%dT%H-00-00-000Z")
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        path = self.directory / f"xauusd_ticks_{key}.json"
        if not path.exists():
            value = None
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not raw:
                value = None
            else:
                array = np.asarray(raw, dtype=float)
                order = np.argsort(array[:, 0], kind="stable")
                array = array[order]
                value = (array[:, 0], array[:, 1], array[:, 2])
        self.cache[key] = value
        while len(self.cache) > self.max_hours:
            self.cache.popitem(last=False)
        return value

    def range(self, start: pd.Timestamp, end: pd.Timestamp):
        hour = start.floor("h")
        end_hour = end.floor("h")
        blocks = []
        missing = []
        while hour <= end_hour:
            block = self.hour(hour)
            if block is None:
                missing.append(hour.isoformat())
            else:
                blocks.append(block)
            hour += pd.Timedelta(hours=1)
        if missing or not blocks:
            return None, missing
        ts = np.concatenate([b[0] for b in blocks])
        ask = np.concatenate([b[1] for b in blocks])
        bid = np.concatenate([b[2] for b in blocks])
        keep = (ts >= start.timestamp() * 1000 - 2000) & (ts <= end.timestamp() * 1000 + 2000)
        return (ts[keep], ask[keep], bid[keep]), []


def _quote_at(ts: np.ndarray, values: np.ndarray, target_ms: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positions = np.searchsorted(ts, target_ms, side="right") - 1
    positions = np.clip(positions, 0, len(ts) - 1)
    return values[positions], (target_ms - ts[positions]) / 1000.0


def _trailing_volatility(move: np.ndarray, ages: np.ndarray, window_seconds: int = 120) -> np.ndarray:
    result = np.zeros(len(move), dtype=float)
    for i, age in enumerate(ages):
        lo = np.searchsorted(ages, age - window_seconds, side="left")
        segment = np.diff(move[lo : i + 1])
        result[i] = float(np.std(segment, ddof=0)) if len(segment) else 0.0
    return result


def build_trade_panel(row: pd.Series, cache: TickHourCache) -> tuple[pd.DataFrame | None, dict]:
    open_time = row.open_time_utc
    close_time = row.close_time_utc
    duration = (close_time - open_time).total_seconds()
    trajectory, missing = cache.range(open_time, close_time)
    audit = {"ticket": str(row.ticket), "missing_hours": missing, "duration_seconds": duration}
    if trajectory is None or duration <= 0:
        audit["status"] = "EXCLUDED_MISSING_TICKS_OR_DURATION"
        return None, audit
    ts, ask, bid = trajectory
    if len(ts) == 0:
        audit["status"] = "EXCLUDED_EMPTY_RANGE"
        return None, audit

    ages = np.arange(GRID_SECONDS, duration, GRID_SECONDS, dtype=float)
    ages = np.r_[ages, duration]
    targets = open_time.timestamp() * 1000 + ages * 1000
    exit_quote = bid if row.side == "Buy" else ask
    prices, stale = _quote_at(ts, exit_quote, targets)
    spreads, _ = _quote_at(ts, ask - bid, targets)
    if np.max(stale) > 10 or np.min(stale) < -1:
        audit.update(status="EXCLUDED_STALE_QUOTES", max_quote_staleness_seconds=float(np.max(stale)))
        return None, audit

    direction = 1.0 if row.side == "Buy" else -1.0
    move = direction * (prices - float(row.entry_exec_price))
    mfe = np.maximum.accumulate(np.maximum(move, 0.0))
    mae = np.maximum.accumulate(np.maximum(-move, 0.0))

    def lagged_move(seconds: int) -> np.ndarray:
        lag_targets = targets - seconds * 1000
        lag_prices, _ = _quote_at(ts, exit_quote, lag_targets)
        return direction * (prices - lag_prices)

    starts = targets - GRID_SECONDS * 1000
    tick_counts = np.searchsorted(ts, targets, side="right") - np.searchsorted(ts, starts, side="right")
    timestamps = open_time + pd.to_timedelta(ages, unit="s")
    seconds = timestamps.hour * 3600 + timestamps.minute * 60 + timestamps.second
    frame = pd.DataFrame(
        {
            "ticket": str(row.ticket),
            "open_time_utc": open_time,
            "timestamp": timestamps,
            "age_seconds": ages,
            "event": np.r_[np.zeros(len(ages) - 1, dtype=int), 1],
            "side_buy": float(row.side == "Buy"),
            "unrealized_move": move,
            "mfe": mfe,
            "mae": mae,
            "drawdown_from_mfe": mfe - move,
            "momentum_30s": lagged_move(30),
            "momentum_120s": lagged_move(120),
            "volatility_120s": _trailing_volatility(move, ages),
            "spread": spreads,
            "tick_rate_15s": tick_counts / GRID_SECONDS,
            "log_age": np.log1p(ages),
            "age_hinge_3m": np.maximum(ages - 180, 0) / 60,
            "age_hinge_10m": np.maximum(ages - 600, 0) / 60,
            "age_hinge_30m": np.maximum(ages - 1800, 0) / 60,
            "age_hinge_60m": np.maximum(ages - 3600, 0) / 60,
            "tod_sin_1": np.sin(2 * np.pi * seconds / 86400),
            "tod_cos_1": np.cos(2 * np.pi * seconds / 86400),
            "tod_sin_2": np.sin(4 * np.pi * seconds / 86400),
            "tod_cos_2": np.cos(4 * np.pi * seconds / 86400),
            "tod_sin_3": np.sin(6 * np.pi * seconds / 86400),
            "tod_cos_3": np.cos(6 * np.pi * seconds / 86400),
        }
    )
    dow = timestamps.dayofweek.to_numpy()
    for value in range(1, 5):
        frame[f"dow_{value}"] = (dow == value).astype(float)
    audit.update(
        status="INCLUDED",
        panel_rows=int(len(frame)),
        max_quote_staleness_seconds=float(np.max(stale)),
        exit_quote_staleness_seconds=float(stale[-1]),
    )
    return frame, audit


def build_panel(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cache = TickHourCache(TICKS)
    frames = []
    audits = []
    for index, row in trades.iterrows():
        frame, audit = build_trade_panel(row, cache)
        audits.append(audit)
        if frame is not None:
            frames.append(frame)
        if (index + 1) % 50 == 0:
            print(f"built causal exit panel for {index + 1}/{len(trades)} trades", flush=True)
    if not frames:
        raise RuntimeError("No trades passed raw-tick coverage checks")
    return pd.concat(frames, ignore_index=True), pd.DataFrame(audits)


def log_likelihood(y: np.ndarray, probability: np.ndarray) -> float:
    probability = np.clip(probability, 1e-9, 1 - 1e-9)
    return float(np.sum(y * np.log(probability) + (1 - y) * np.log1p(-probability)))


def fit_model(train: pd.DataFrame, validation: pd.DataFrame, features: list[str]) -> tuple[Pipeline, float, list[dict]]:
    candidates = []
    best = None
    for c_value in (0.001, 0.01, 0.1, 1.0, 10.0):
        model = Pipeline(
            [
                ("scale", StandardScaler()),
                ("logit", LogisticRegression(C=c_value, solver="lbfgs", max_iter=3000, random_state=SEED)),
            ]
        )
        model.fit(train[features], train.event)
        ll = log_likelihood(validation.event.to_numpy(), model.predict_proba(validation[features])[:, 1])
        candidates.append({"C": c_value, "validation_log_likelihood": ll})
        if best is None or ll > best[0]:
            best = (ll, c_value)
    assert best is not None
    selected_c = float(best[1])
    combined = pd.concat([train, validation], ignore_index=True)
    frozen = Pipeline(
        [
            ("scale", StandardScaler()),
            ("logit", LogisticRegression(C=selected_c, solver="lbfgs", max_iter=3000, random_state=SEED)),
        ]
    )
    frozen.fit(combined[features], combined.event)
    return frozen, selected_c, candidates


def per_trade_ll(frame: pd.DataFrame, probability: np.ndarray) -> pd.Series:
    y = frame.event.to_numpy()
    probability = np.clip(probability, 1e-9, 1 - 1e-9)
    contribution = y * np.log(probability) + (1 - y) * np.log1p(-probability)
    return pd.Series(contribution).groupby(frame.ticket.reset_index(drop=True)).sum()


def sign_flip_pvalue(values: np.ndarray, permutations: int = 20000, seed: int = SEED) -> float:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return 1.0
    observed = float(np.mean(values))
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(permutations):
        statistic = float(np.mean(values * rng.choice((-1.0, 1.0), size=len(values))))
        exceed += statistic >= observed
    return (exceed + 1) / (permutations + 1)


def holm_adjust(pvalues: list[float]) -> list[float]:
    pvalues = np.asarray(pvalues, dtype=float)
    order = np.argsort(pvalues)
    adjusted = np.empty(len(pvalues), dtype=float)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(pvalues) - rank) * pvalues[index])
        adjusted[index] = min(running, 1.0)
    return adjusted.tolist()


def time_rescaling_test(frame: pd.DataFrame, probability: np.ndarray) -> dict:
    work = frame[["ticket"]].copy()
    work["hazard"] = np.clip(probability, 1e-9, 1 - 1e-9)
    cumulative_hazard = work.assign(h=-np.log1p(-work.hazard)).groupby("ticket").h.sum()
    transformed = 1 - np.exp(-cumulative_hazard.to_numpy())
    statistic, pvalue = stats.kstest(transformed, "uniform")
    return {
        "n_trades": int(len(transformed)),
        "ks_statistic": float(statistic),
        "ks_pvalue": float(pvalue),
        "mean_transformed": float(np.mean(transformed)),
        "gate": "PASS" if pvalue >= 0.05 else "FAIL",
    }


def evaluate_models(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    discovery = panel[panel.open_time_utc < LOCKBOX_START].copy()
    lockbox = panel[panel.open_time_utc >= LOCKBOX_START].copy()
    discovery_tickets = (
        discovery[["ticket", "open_time_utc"]].drop_duplicates().sort_values("open_time_utc").reset_index(drop=True)
    )
    inner_cut = discovery_tickets.open_time_utc.quantile(0.75)
    train = discovery[discovery.open_time_utc < inner_cut]
    validation = discovery[discovery.open_time_utc >= inner_cut]

    baseline, baseline_c, baseline_selection = fit_model(train, validation, BASE_FEATURES)
    baseline_probability = baseline.predict_proba(lockbox[BASE_FEATURES])[:, 1]
    baseline_ll = log_likelihood(lockbox.event.to_numpy(), baseline_probability)
    baseline_trade_ll = per_trade_ll(lockbox, baseline_probability)
    baseline_rescaling = time_rescaling_test(lockbox, baseline_probability)

    specifications = [(feature, BASE_FEATURES + [feature]) for feature in MARKET_FEATURES]
    specifications.append(("combined_market_state", BASE_FEATURES + MARKET_FEATURES))
    rows = []
    fitted = {}
    for model_index, (name, features) in enumerate(specifications):
        model, selected_c, selection = fit_model(train, validation, features)
        probability = model.predict_proba(lockbox[features])[:, 1]
        ll = log_likelihood(lockbox.event.to_numpy(), probability)
        trade_ll = per_trade_ll(lockbox, probability)
        common = baseline_trade_ll.index.intersection(trade_ll.index)
        delta = (trade_ll.loc[common] - baseline_trade_ll.loc[common]).to_numpy()
        coefficient = float(model.named_steps["logit"].coef_[0][-1]) if name != "combined_market_state" else math.nan
        rows.append(
            {
                "model": name,
                "market_feature_count": len(features) - len(BASE_FEATURES),
                "selected_C": selected_c,
                "lockbox_log_likelihood": ll,
                "lockbox_incremental_bits_per_exit": (ll - baseline_ll) / (math.log(2) * lockbox.event.sum()),
                "mean_trade_log_likelihood_delta": float(np.mean(delta)),
                "raw_sign_flip_pvalue": sign_flip_pvalue(delta, seed=SEED + model_index),
                "standardized_feature_coefficient": coefficient,
            }
        )
        fitted[name] = {
            "features": features,
            "selected_C": selected_c,
            "regularization_selection": selection,
            "time_rescaling": time_rescaling_test(lockbox, probability),
        }
    table = pd.DataFrame(rows)
    table["holm_pvalue"] = holm_adjust(table.raw_sign_flip_pvalue.tolist())
    table["survives_lockbox_gate"] = (
        (table.lockbox_incremental_bits_per_exit > 0) & (table.holm_pvalue < 0.05)
    )
    metadata = {
        "lockbox_start_utc": LOCKBOX_START.isoformat(),
        "inner_discovery_cut_utc": inner_cut.isoformat(),
        "discovery_trades": int(discovery.ticket.nunique()),
        "lockbox_trades": int(lockbox.ticket.nunique()),
        "discovery_rows": int(len(discovery)),
        "lockbox_rows": int(len(lockbox)),
        "grid_seconds": GRID_SECONDS,
        "baseline": {
            "features": BASE_FEATURES,
            "selected_C": baseline_c,
            "regularization_selection": baseline_selection,
            "lockbox_log_likelihood": baseline_ll,
            "time_rescaling": baseline_rescaling,
        },
        "models": fitted,
    }
    return table, metadata


def render_report(result: dict, table: pd.DataFrame) -> str:
    survivors = table.loc[table.survives_lockbox_gate, "model"].tolist()
    combined = table.loc[table.model == "combined_market_state"].iloc[0]
    lines = [
        "# CTPI exit investigation",
        "",
        "## Decision",
        "",
        result["decision"],
        "",
        "Entry discovery remains frozen. This analysis does not reuse the entry lockbox for a new entry search.",
        "",
        "## Design",
        "",
        f"- Canonical trades: {result['coverage']['canonical_trades']}",
        f"- Raw-tick-complete trades: {result['coverage']['included_trades']}",
        f"- Discovery/lockbox trades: {result['model_metadata']['discovery_trades']} / {result['model_metadata']['lockbox_trades']}",
        f"- Lockbox starts: {result['model_metadata']['lockbox_start_utc']}",
        f"- Causal risk-set interval: {GRID_SECONDS} seconds",
        "- Baseline: flexible holding age, side, UTC time of day, and weekday.",
        "- Candidate state: executable move, MFE, MAE, peak retracement, short momentum, volatility, spread, and tick rate.",
        "- Positive gate: incremental lockbox information above zero and Holm-adjusted sign-flip p < 0.05.",
        "",
        "## Lockbox results",
        "",
        "| model | bits per exit vs baseline | Holm p | gate | standardized coefficient |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for row in table.itertuples(index=False):
        coef = "n.a." if not np.isfinite(row.standardized_feature_coefficient) else f"{row.standardized_feature_coefficient:.4f}"
        lines.append(
            f"| {row.model} | {row.lockbox_incremental_bits_per_exit:.4f} | {row.holm_pvalue:.4g} | "
            f"{'PASS' if row.survives_lockbox_gate else 'FAIL'} | {coef} |"
        )
    lines.extend(
        [
            "",
            f"Surviving predeclared models: {', '.join(survivors) if survivors else 'none'}.",
            "",
            "## Absolute goodness of fit",
            "",
            f"The combined model time-rescaling gate is **{result['combined_time_rescaling']['gate']}** "
            f"(KS p={result['combined_time_rescaling']['ks_pvalue']:.4g}).",
            "",
            "A market-state association is only a partial exit component. A complete exit mechanism also needs "
            "absolute calibration and deterministic sequential replay. Public ticks cannot establish broker-side "
            "stop/target modifications or the unique original source code.",
            "",
            "## Evidence exclusions",
            "",
            "The old `phase8c_exit_falsification.py` candidate table is excluded because several candidate rows are "
            "literal hard-coded numbers rather than computed results. The older M1 walk-forward table remains "
            "historical descriptive evidence, not this confirmatory raw-tick test.",
            "",
            "## Mathematical interpretation",
            "",
            "For each open trade and interval, the model estimates `P(exit in the next interval | still open, age, "
            "calendar, market state)`. The reported bits are `(LL_state - LL_baseline)/(N_exits ln 2)` on the "
            "untouched chronological lockbox. Therefore a positive value measures exit-timing information beyond "
            "the age/session clock; it does not by itself prove a deterministic rule.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    ledger_hash = sha256(LEDGER)
    if ledger_hash != EXPECTED_LEDGER_SHA256:
        raise RuntimeError(f"Canonical ledger hash mismatch: {ledger_hash}")
    trades = pd.read_csv(RECON, dtype={"ticket": str})
    if len(trades) != 423:
        raise RuntimeError(f"Expected 423 canonical trades, found {len(trades)}")
    trades["open_time_utc"] = pd.to_datetime(trades.open_time_utc, utc=True)
    trades["close_time_utc"] = pd.to_datetime(trades.close_time_utc, utc=True)
    trades = trades.sort_values(["open_time_utc", "ticket"]).reset_index(drop=True)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel, coverage = build_panel(trades)
    panel.to_parquet(OUTPUT / "exit_risk_panel.parquet", index=False)
    coverage.to_csv(OUTPUT / "raw_tick_coverage.csv", index=False)
    table, metadata = evaluate_models(panel)
    table.to_csv(OUTPUT / "lockbox_feature_tests.csv", index=False)

    survivors = table.loc[table.survives_lockbox_gate, "model"].tolist()
    combined_rescaling = metadata["models"]["combined_market_state"]["time_rescaling"]
    if survivors and combined_rescaling["gate"] == "PASS":
        decision = "Partial exit-state information is identified; proceed only to discovery-frozen symbolic replay."
        taxonomy = "PARTIAL_EXIT_COMPONENTS_IDENTIFIED"
    elif survivors:
        decision = "Some exit-state features carry lockbox information, but the absolute exit model fails calibration."
        taxonomy = "ASSOCIATION_WITHOUT_ABSOLUTE_EXIT_MODEL"
    else:
        decision = "No tested market-state exit feature survives the chronological lockbox gate beyond age and calendar."
        taxonomy = "TESTED_EXIT_FEATURES_NOT_IDENTIFIED"
    result = {
        "status": "complete",
        "taxonomy": taxonomy,
        "decision": decision,
        "canonical_hashes": {
            "data/raw/trades_raw.tsv": ledger_hash,
            "outputs/market_reconstruction/phase7c_trade_reconciliation.csv": sha256(RECON),
        },
        "coverage": {
            "canonical_trades": int(len(trades)),
            "included_trades": int((coverage.status == "INCLUDED").sum()),
            "excluded_trades": int((coverage.status != "INCLUDED").sum()),
            "status_counts": {str(k): int(v) for k, v in coverage.status.value_counts().items()},
        },
        "surviving_models": survivors,
        "combined_time_rescaling": combined_rescaling,
        "model_metadata": metadata,
        "limitations": [
            "Public raw XAUUSD ticks are not the original broker/account quote stream.",
            "Orders, deals, stop/target modifications, costs, and hidden account state are unavailable.",
            "A hazard association is not a unique deterministic exit algorithm.",
        ],
    }
    (OUTPUT / "exit_recoverability_verdict.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUTPUT / "CTPI_EXIT_REPORT.md").write_text(render_report(result, table), encoding="utf-8")
    print(json.dumps({"taxonomy": taxonomy, "survivors": survivors, "coverage": result["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
