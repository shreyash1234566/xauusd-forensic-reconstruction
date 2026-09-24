"""
Phase 10/11 — Tick Feature Extraction Module
=============================================
Extracts pre-entry tick features for case-control analysis.

Feature set for M3/M4 models (8 features):
  jump_z       : absolute mid-price move in 30s window, Z-scored by hour-level baseline
  disp30       : total path (sum of |tick_mid_diff|) in 30s window
  tick_rate_30 : tick arrival rate in 30s window (ticks/sec)
  tick_rate_ratio : tick_rate_30 / tick_rate_300 (short vs. 5-min rate)
  spread_now   : bid-ask spread at entry tick
  spread_ratio : spread_now / spread_300 (5-min rolling mean spread)
  ret5         : signed mid return from 5s before entry
  n_ticks_300  : total tick count in 300s (5min) window before entry

All features are computed STRICTLY from ticks BEFORE the case/control timestamp
(causal: no tick at or after target_ms is included in features).
"""

from pathlib import Path
from datetime import timedelta
import json
import numpy as np
import pandas as pd
from typing import Optional, Tuple, Iterable, Union
from collections import OrderedDict


ROOT = Path(__file__).resolve().parent.parent
TICKS_DIR = ROOT / "data" / "market" / "raw_ticks"


class TickStore:
    """
    Cached loader for hourly tick JSON files.
    Tick file format: [[timestamp_ms, ask, bid, ask_vol, bid_vol], ...]
    """
    def __init__(self, ticks_dir: Union[Path, str] = TICKS_DIR):
        self.ticks_dir = Path(ticks_dir)
        self.maxsize = 8
        self._cache: OrderedDict = OrderedDict()
        self._cache_arrays: OrderedDict = OrderedDict()

    def _load_hour_arrays(self, dt_utc: pd.Timestamp) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Load ticks as (ts_ms, mid, spread) NumPy arrays for dt_utc hour."""
        hour_dt = dt_utc.replace(minute=0, second=0, microsecond=0, nanosecond=0)
        if hasattr(hour_dt, "tzinfo") and hour_dt.tzinfo is not None:
            hour_dt = hour_dt.tz_convert("UTC")

        iso_str = hour_dt.strftime("%Y-%m-%dT%H-00-00-000Z")
        if iso_str in self._cache_arrays:
            self._cache_arrays.move_to_end(iso_str)
            return self._cache_arrays[iso_str]

        df = self._load_hour(hour_dt)
        if df is None or len(df) == 0:
            self._cache_arrays[iso_str] = None
            if len(self._cache_arrays) > self.maxsize:
                self._cache_arrays.popitem(last=False)
            return None

        ts_ms = df["ts_ms"].to_numpy(dtype=np.int64, copy=False)
        mid = df["mid"].to_numpy(dtype=np.float64, copy=False)
        spread = df["spread"].to_numpy(dtype=np.float64, copy=False)
        res = (ts_ms, mid, spread)
        self._cache_arrays[iso_str] = res
        if len(self._cache_arrays) > self.maxsize:
            self._cache_arrays.popitem(last=False)
        return res

    def _load_hour(self, dt_utc: pd.Timestamp) -> Optional[pd.DataFrame]:
        """Load ticks for the UTC hour containing dt_utc."""
        hour_dt = dt_utc.replace(minute=0, second=0, microsecond=0, nanosecond=0)
        if hasattr(hour_dt, "tzinfo") and hour_dt.tzinfo is not None:
            hour_dt = hour_dt.tz_convert("UTC")

        iso_str = hour_dt.strftime("%Y-%m-%dT%H-00-00-000Z")
        if iso_str in self._cache:
            self._cache.move_to_end(iso_str)
            return self._cache[iso_str]

        p = self.ticks_dir / f"xauusd_ticks_{iso_str}.json"
        if not p.exists():
            self._cache[iso_str] = None
            if len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)
            return None

        try:
            with open(p, "r") as f:
                data = json.load(f)
            if not data:
                self._cache[iso_str] = None
                if len(self._cache) > self.maxsize:
                    self._cache.popitem(last=False)
                return None
            arr = np.array(data, dtype=np.float64)
            df = pd.DataFrame({
                "ts_ms": arr[:, 0].astype(np.int64),
                "ask": arr[:, 1],
                "bid": arr[:, 2],
                "mid": (arr[:, 1] + arr[:, 2]) / 2.0,
                "spread": arr[:, 1] - arr[:, 2],
            })
            df = df.drop_duplicates(subset=["ts_ms"]).sort_values("ts_ms").reset_index(drop=True)
            self._cache[iso_str] = df
            if len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)
            return df
        except Exception as e:
            self._cache[iso_str] = None
            if len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)
            return None

    def get_window_arrays(
        self,
        target_ms: int,
        lookback_sec: float = 310.0,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """
        Return (ts_ms, mid, spread) NumPy arrays in [target_ms - lookback_sec*1000, target_ms).
        Causal contract: ts_ms strictly < target_ms.
        """
        start_ms = int(target_ms - lookback_sec * 1000)
        end_ms = int(target_ms)

        start_dt = pd.Timestamp(start_ms * 1_000_000, unit="ns", tz="UTC")
        end_dt = pd.Timestamp(end_ms * 1_000_000, unit="ns", tz="UTC")

        ts_list = []
        mid_list = []
        spread_list = []

        h = start_dt.replace(minute=0, second=0, microsecond=0, nanosecond=0)
        while h <= end_dt:
            arrs = self._load_hour_arrays(h)
            if arrs is not None:
                ts_vals, mid_vals, sp_vals = arrs
                left = int(np.searchsorted(ts_vals, start_ms, side="left"))
                right = int(np.searchsorted(ts_vals, end_ms, side="left"))
                if left < right:
                    ts_list.append(ts_vals[left:right])
                    mid_list.append(mid_vals[left:right])
                    spread_list.append(sp_vals[left:right])
            h += pd.Timedelta(hours=1)

        if not ts_list:
            return None

        if len(ts_list) == 1:
            return ts_list[0], mid_list[0], spread_list[0]

        concat_ts = np.concatenate(ts_list)
        concat_mid = np.concatenate(mid_list)
        concat_sp = np.concatenate(spread_list)

        _, unique_indices = np.unique(concat_ts, return_index=True)
        unique_indices.sort()

        return concat_ts[unique_indices], concat_mid[unique_indices], concat_sp[unique_indices]

    def get_window(
        self,
        target_ms: int,
        lookback_sec: float = 310.0,
        lookahead_sec: float = 0.0,
    ) -> Optional[pd.DataFrame]:
        """
        Return all ticks in [target_ms - lookback_sec*1000, target_ms + lookahead_sec*1000).

        CAUSAL CONTRACT: lookahead_sec=0.0 means ticks strictly BEFORE target_ms.
        The target tick itself (ts_ms == target_ms) is EXCLUDED to avoid self-inclusion.

        Parameters
        ----------
        target_ms    : int, target timestamp in Unix milliseconds
        lookback_sec : float, window length in seconds (default 310 = 5m10s to cover 300s robustly)
        lookahead_sec: float, MUST be 0.0 for causal feature extraction

        Returns
        -------
        pd.DataFrame with columns [ts_ms, ask, bid, mid, spread], or None if no ticks
        """
        assert lookahead_sec == 0.0, "Lookahead must be 0 for causal extraction"

        start_ms = int(target_ms - lookback_sec * 1000)
        end_ms = int(target_ms)  # exclusive upper bound (< target_ms)

        # Determine which hours overlap
        start_dt = pd.Timestamp(start_ms * 1_000_000, unit="ns", tz="UTC")
        end_dt = pd.Timestamp(end_ms * 1_000_000, unit="ns", tz="UTC")

        # Each cached hourly frame is already sorted and deduplicated by
        # _load_hour().  Slice it with binary search before concatenating so
        # that a control event never materializes the full hourly frames in a
        # temporary DataFrame.  The old implementation concatenated every
        # overlapping hour, then globally copied, deduplicated, and sorted it
        # for every event (millions of repeated allocations).
        frames = []
        h = start_dt.replace(minute=0, second=0, microsecond=0, nanosecond=0)
        while h <= end_dt:
            df = self._load_hour(h)
            if df is not None:
                ts_values = df["ts_ms"].to_numpy(dtype=np.int64, copy=False)
                left = int(np.searchsorted(ts_values, start_ms, side="left"))
                right = int(np.searchsorted(ts_values, end_ms, side="left"))
                if left < right:
                    frames.append(df.iloc[left:right])
            h += pd.Timedelta(hours=1)

        if not frames:
            return None

        # The concatenation order is increasing UTC hour, matching the old
        # behavior where drop_duplicates() kept the first occurrence in the
        # concatenated stream.
        windowed = pd.concat(frames, ignore_index=True)

        # Match the old semantics order: drop_duplicates (keep first), then
        # sort_values by ts_ms.
        windowed = windowed.drop_duplicates(subset=["ts_ms"], keep="first")
        windowed = windowed.sort_values("ts_ms")

        # Defensive boundary filter (should be redundant given searchsorted).
        windowed = windowed[(windowed["ts_ms"] >= start_ms) & (windowed["ts_ms"] < end_ms)]

        if len(windowed) == 0:
            return None

        return windowed.reset_index(drop=True)


def extract_tick_features(
    ticks: Optional[pd.DataFrame],
    target_ms: int,
    hour_baselines: Optional[dict] = None,
) -> dict:
    """
    Compute the 8 tick features for one case or control event.

    Parameters
    ----------
    ticks         : DataFrame from TickStore.get_window (already causal: < target_ms)
    target_ms     : int, target event timestamp in milliseconds
    hour_baselines: dict keyed by UTC hour (0-23), each value is dict with
                    keys 'spread_mean', 'tick_rate_mean', 'abs_move_std'
                    Used to Z-score jump_z. If None, Z-scores are unscaled.

    Returns
    -------
    dict with 8 features + coverage metadata
    """
    NaN = np.nan
    feats = {
        "jump_z":         NaN,
        "disp30":         NaN,
        "tick_rate_30":   NaN,
        "tick_rate_ratio": NaN,
        "spread_now":     NaN,
        "spread_ratio":   NaN,
        "ret5":           NaN,
        "n_ticks_300":    NaN,
        "tick_coverage":  0.0,   # fraction of 300s window with ticks
    }

    if ticks is None or len(ticks) == 0:
        feats["tick_coverage"] = 0.0
        return feats

    # Most recent tick before target
    last_tick = ticks.iloc[-1]
    feats["spread_now"] = float(last_tick["spread"])
    utc_hour = (target_ms // 3_600_000) % 24
    feats["utc_hour"] = utc_hour

    # ── n_ticks_300: ticks in past 300s ───────────────────────────────────
    t300_start = target_ms - 300_000
    mask_300 = ticks["ts_ms"] >= t300_start
    ticks_300 = ticks[mask_300]
    n_300 = len(ticks_300)
    feats["n_ticks_300"] = float(n_300)

    # Coverage estimate: if earliest tick in 300s window is within 5s of t300_start, full coverage
    if n_300 > 0:
        earliest_300 = int(ticks_300["ts_ms"].iloc[0])
        feats["tick_coverage"] = min(1.0, (target_ms - earliest_300) / 300_000)
    else:
        feats["tick_coverage"] = 0.0

    # ── tick_rate_300: ticks per second over 300s window ──────────────────
    tick_rate_300 = n_300 / 300.0 if n_300 > 0 else 0.0

    # ── 30s window features ───────────────────────────────────────────────
    t30_start = target_ms - 30_000
    ticks_30 = ticks[ticks["ts_ms"] >= t30_start]
    n_30 = len(ticks_30)

    if n_30 >= 2:
        mid_30 = ticks_30["mid"].values
        abs_move_30 = abs(mid_30[-1] - mid_30[0])      # jump
        disp_30 = float(np.sum(np.abs(np.diff(mid_30))))  # total path
        feats["raw_abs_move_30"] = float(abs_move_30)
        feats["disp30"] = disp_30
        feats["tick_rate_30"] = float(n_30) / 30.0

        # Z-score jump by hour baseline
        utc_hour = (target_ms // 3_600_000) % 24
        if hour_baselines and utc_hour in hour_baselines:
            bl = hour_baselines[utc_hour]
            std_move = bl.get("abs_move_std", 1.0) or 1.0
            feats["jump_z"] = abs_move_30 / std_move
            mean_spread = bl.get("spread_mean", 1.0) or 1.0
            feats["spread_ratio"] = feats["spread_now"] / mean_spread
        else:
            # No discovery baseline means the standardized jump feature is
            # unavailable; never substitute an unscaled or zero-filled value.
            feats["jump_z"] = NaN

        # tick_rate_ratio: 30s rate / 300s rate
        if tick_rate_300 > 0:
            feats["tick_rate_ratio"] = feats["tick_rate_30"] / tick_rate_300
        else:
            feats["tick_rate_ratio"] = NaN

    else:
        feats["raw_abs_move_30"] = NaN
        feats["n_ticks_300"] = float(n_300)
        feats["tick_rate_30"] = float(n_30) / 30.0 if n_30 > 0 else 0.0

    # ── ret5: signed mid return over 5s window ────────────────────────────
    t5_start = target_ms - 5_000
    ticks_5 = ticks[ticks["ts_ms"] >= t5_start]
    if len(ticks_5) >= 2:
        feats["ret5"] = float(ticks_5.iloc[-1]["mid"] - ticks_5.iloc[0]["mid"])
    elif len(ticks_5) == 1 and n_30 >= 1:
        # Use 30s reference if 5s only has 1 tick
        ref_mid = ticks_30.iloc[0]["mid"] if n_30 >= 1 else last_tick["mid"]
        feats["ret5"] = float(last_tick["mid"] - ref_mid)
    else:
        # A missing return is unavailable, not a zero return.
        feats["ret5"] = NaN

    # ── spread_ratio: fallback if no hour baseline ─────────────────────────
    if n_300 > 0:
        mean_spread_300 = float(ticks_300["spread"].mean())
        feats["raw_mean_spread_300"] = mean_spread_300
        if np.isnan(feats["spread_ratio"]):
            feats["spread_ratio"] = feats["spread_now"] / max(mean_spread_300, 1e-6)
    else:
        feats["raw_mean_spread_300"] = NaN

    return feats


def extract_tick_features_arrays(
    arrs: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]],
    target_ms: int,
    hour_baselines: Optional[dict] = None,
) -> dict:
    """
    Compute the 8 tick features directly from NumPy arrays (ts_ms, mid, spread).
    100% numerically and causally identical to extract_tick_features.
    """
    NaN = np.nan
    feats = {
        "jump_z":         NaN,
        "disp30":         NaN,
        "tick_rate_30":   NaN,
        "tick_rate_ratio": NaN,
        "spread_now":     NaN,
        "spread_ratio":   NaN,
        "ret5":           NaN,
        "n_ticks_300":    NaN,
        "tick_coverage":  0.0,
        "utc_hour":       float((int(target_ms) // 3_600_000) % 24),
        "raw_abs_move_30": NaN,
        "raw_mean_spread_300": NaN,
    }

    if arrs is None or len(arrs[0]) == 0:
        feats["tick_coverage"] = 0.0
        return feats

    ts_ms, mid, spread = arrs
    n_total = len(ts_ms)

    # Most recent tick before target
    feats["spread_now"] = float(spread[-1])

    # ── n_ticks_300: ticks in past 300s ───────────────────────────────────
    t300_start = target_ms - 300_000
    idx_300 = int(np.searchsorted(ts_ms, t300_start, side="left"))
    n_300 = n_total - idx_300
    feats["n_ticks_300"] = float(n_300)

    # Coverage estimate: if earliest tick in 300s window is within 5s of t300_start, full coverage
    if n_300 > 0:
        earliest_300 = int(ts_ms[idx_300])
        feats["tick_coverage"] = min(1.0, (target_ms - earliest_300) / 300_000.0)
    else:
        feats["tick_coverage"] = 0.0

    # ── tick_rate_300: ticks per second over 300s window ──────────────────
    tick_rate_300 = n_300 / 300.0 if n_300 > 0 else 0.0

    # ── 30s window features ───────────────────────────────────────────────
    t30_start = target_ms - 30_000
    idx_30 = int(np.searchsorted(ts_ms, t30_start, side="left"))
    n_30 = n_total - idx_30

    utc_hour = (target_ms // 3_600_000) % 24
    feats["utc_hour"] = utc_hour

    if n_30 >= 2:
        mid_30 = mid[idx_30:]
        abs_move_30 = abs(mid_30[-1] - mid_30[0])      # jump
        disp_30 = float(np.sum(np.abs(np.diff(mid_30))))  # total path
        feats["raw_abs_move_30"] = float(abs_move_30)
        feats["disp30"] = disp_30
        feats["tick_rate_30"] = float(n_30) / 30.0

        # Z-score jump by hour baseline
        if hour_baselines and utc_hour in hour_baselines:
            bl = hour_baselines[utc_hour]
            std_move = bl.get("abs_move_std", 1.0) or 1.0
            feats["jump_z"] = abs_move_30 / std_move
            mean_spread = bl.get("spread_mean", 1.0) or 1.0
            feats["spread_ratio"] = feats["spread_now"] / mean_spread
        else:
            feats["jump_z"] = NaN

        # tick_rate_ratio: 30s rate / 300s rate
        if tick_rate_300 > 0:
            feats["tick_rate_ratio"] = feats["tick_rate_30"] / tick_rate_300
        else:
            feats["tick_rate_ratio"] = NaN

    else:
        feats["raw_abs_move_30"] = NaN
        feats["n_ticks_300"] = float(n_300)
        feats["tick_rate_30"] = float(n_30) / 30.0 if n_30 > 0 else 0.0

    # ── ret5: signed mid return over 5s window ────────────────────────────
    t5_start = target_ms - 5_000
    idx_5 = int(np.searchsorted(ts_ms, t5_start, side="left"))
    n_5 = n_total - idx_5
    if n_5 >= 2:
        feats["ret5"] = float(mid[-1] - mid[idx_5])
    elif n_5 == 1 and n_30 >= 1:
        # Use 30s reference if 5s only has 1 tick
        ref_mid = mid[idx_30] if n_30 >= 1 else mid[-1]
        feats["ret5"] = float(mid[-1] - ref_mid)
    else:
        feats["ret5"] = NaN

    # ── spread_ratio: fallback if no hour baseline ─────────────────────────
    if n_300 > 0:
        mean_spread_300 = float(np.mean(spread[idx_300:]))
        feats["raw_mean_spread_300"] = mean_spread_300
        if np.isnan(feats["spread_ratio"]):
            feats["spread_ratio"] = feats["spread_now"] / max(mean_spread_300, 1e-6)
    else:
        feats["raw_mean_spread_300"] = NaN

    return feats


def compute_hour_baselines(
    all_case_ticks: dict,
    all_control_ticks: dict,
) -> dict:
    """
    Compute per-UTC-hour tick baseline statistics from discovery-period ticks.
    Used to Z-score jump_z and spread_ratio.

    Parameters
    ----------
    all_case_ticks    : dict {trade_idx -> {'target_ms': int, 'ticks': DataFrame}}
    all_control_ticks : dict {ctrl_idx  -> {'target_ms': int, 'ticks': DataFrame}}

    Returns
    -------
    dict{hour: {'abs_move_std': float, 'spread_mean': float, 'tick_rate_mean': float}}
    """
    hour_moves = {h: [] for h in range(24)}
    hour_spreads = {h: [] for h in range(24)}
    hour_rates = {h: [] for h in range(24)}

    for events in [all_case_ticks, all_control_ticks]:
        for idx, entry in events.items():
            target_ms = entry["target_ms"]
            ticks = entry["ticks"]
            if ticks is None or len(ticks) == 0:
                continue
            utc_hour = (target_ms // 3_600_000) % 24

            t30_start = target_ms - 30_000
            ticks_30 = ticks[ticks["ts_ms"] >= t30_start]
            if len(ticks_30) >= 2:
                mid_30 = ticks_30["mid"].values
                abs_move = abs(mid_30[-1] - mid_30[0])
                hour_moves[utc_hour].append(abs_move)

            t300_start = target_ms - 300_000
            ticks_300 = ticks[ticks["ts_ms"] >= t300_start]
            if len(ticks_300) > 0:
                hour_spreads[utc_hour].append(float(ticks_300["spread"].mean()))
                hour_rates[utc_hour].append(len(ticks_300) / 300.0)

    baselines = {}
    for h in range(24):
        moves = hour_moves[h]
        spreads = hour_spreads[h]
        rates = hour_rates[h]
        baselines[h] = {
            "abs_move_std": float(np.std(moves)) if len(moves) > 1 else 1.0,
            "spread_mean": float(np.mean(spreads)) if spreads else 1.0,
            "tick_rate_mean": float(np.mean(rates)) if rates else 1.0,
            "n_obs": len(moves),
        }

    return baselines


def compute_hour_baselines_from_raw_features(
    feature_list: list[dict],
) -> dict:
    """
    Compute per-UTC-hour baseline statistics from an in-memory list of extracted raw feature dicts.
    Used for strictly leak-free chronological fold baseline computation.

    Parameters
    ----------
    feature_list : list of dicts containing 'utc_hour', 'raw_abs_move_30', 'raw_mean_spread_300', 'n_ticks_300'

    Returns
    -------
    dict{hour: {'abs_move_std': float, 'spread_mean': float, 'tick_rate_mean': float, 'n_obs': int}}
    """
    hour_moves = {h: [] for h in range(24)}
    hour_spreads = {h: [] for h in range(24)}
    hour_rates = {h: [] for h in range(24)}

    for f in feature_list:
        if f is None or not isinstance(f, dict):
            continue
        h = f.get("utc_hour")
        if h is None or np.isnan(h):
            continue
        h = int(h)

        raw_move = f.get("raw_abs_move_30")
        if raw_move is not None and not np.isnan(raw_move):
            hour_moves[h].append(float(raw_move))

        raw_spread = f.get("raw_mean_spread_300")
        if raw_spread is not None and not np.isnan(raw_spread):
            hour_spreads[h].append(float(raw_spread))

        n_300 = f.get("n_ticks_300")
        if n_300 is not None and not np.isnan(n_300):
            hour_rates[h].append(float(n_300) / 300.0)

    baselines = {}
    for h in range(24):
        moves = hour_moves[h]
        spreads = hour_spreads[h]
        rates = hour_rates[h]
        baselines[h] = {
            "abs_move_std": float(np.std(moves)) if len(moves) > 1 else 1.0,
            "spread_mean": float(np.mean(spreads)) if spreads else 1.0,
            "tick_rate_mean": float(np.mean(rates)) if rates else 1.0,
            "n_obs": len(moves),
        }
    return baselines


def rescale_tick_features_for_baselines(
    feats: dict,
    hour_baselines: dict,
) -> dict:
    """
    Re-scale the baseline-dependent features (jump_z, spread_ratio) of a feature dict
    using the provided hour_baselines without re-extracting ticks.
    """
    if feats is None or not isinstance(feats, dict):
        return feats

    new_f = dict(feats)
    h = new_f.get("utc_hour")
    raw_move = new_f.get("raw_abs_move_30")
    spread_now = new_f.get("spread_now")
    raw_spread = new_f.get("raw_mean_spread_300")

    if h is not None and not np.isnan(h):
        h = int(h)
        if hour_baselines and h in hour_baselines:
            bl = hour_baselines[h]
            std_move = bl.get("abs_move_std", 1.0) or 1.0
            if raw_move is not None and not np.isnan(raw_move):
                new_f["jump_z"] = float(raw_move) / std_move
            else:
                new_f["jump_z"] = np.nan

            mean_spread = bl.get("spread_mean", 1.0) or 1.0
            if spread_now is not None and not np.isnan(spread_now):
                new_f["spread_ratio"] = float(spread_now) / mean_spread
            else:
                new_f["spread_ratio"] = np.nan
        else:
            new_f["jump_z"] = np.nan
            if spread_now is not None and not np.isnan(spread_now) and raw_spread is not None and not np.isnan(raw_spread):
                new_f["spread_ratio"] = float(spread_now) / max(float(raw_spread), 1e-6)
            else:
                new_f["spread_ratio"] = np.nan
    else:
        new_f["jump_z"] = np.nan
        if spread_now is not None and not np.isnan(spread_now) and raw_spread is not None and not np.isnan(raw_spread):
            new_f["spread_ratio"] = float(spread_now) / max(float(raw_spread), 1e-6)
        else:
            new_f["spread_ratio"] = np.nan

    return new_f


def compute_hour_baselines_streaming(
    store: TickStore,
    timestamps: Iterable[Union[str, int, pd.Timestamp]],
    lookback_sec: float = 310.0,
    progress_interval: int = 50000,
) -> dict:
    """
    Compute per-UTC-hour tick baseline statistics streaming across discovery timestamps.
    Maintains bounded memory by discarding tick DataFrames immediately after each timestamp.

    Parameters
    ----------
    store             : TickStore instance
    timestamps        : Iterable of discovery timestamps (cases + controls)
    lookback_sec      : Lookback window in seconds (default: 310.0s)
    progress_interval : Print progress every N timestamps (0 to disable)

    Returns
    -------
    dict{hour: {'abs_move_std': float, 'spread_mean': float, 'tick_rate_mean': float, 'n_obs': int}}
    """
    hour_moves = {h: [] for h in range(24)}
    hour_spreads = {h: [] for h in range(24)}
    hour_rates = {h: [] for h in range(24)}

    for count, ts in enumerate(timestamps, 1):
        if isinstance(ts, (int, np.integer)):
            target_ms = int(ts)
        elif isinstance(ts, pd.Timestamp):
            target_ms = int(ts.timestamp() * 1000)
        else:
            target_ms = int(pd.Timestamp(str(ts)).timestamp() * 1000)

        arrs = store.get_window_arrays(target_ms, lookback_sec=lookback_sec)
        if arrs is not None and len(arrs[0]) > 0:
            ts_ms, mid, spread = arrs
            utc_hour = (target_ms // 3_600_000) % 24

            t30_start = target_ms - 30_000
            idx_30 = int(np.searchsorted(ts_ms, t30_start, side="left"))
            n_30 = len(ts_ms) - idx_30
            if n_30 >= 2:
                mid_30 = mid[idx_30:]
                abs_move = abs(mid_30[-1] - mid_30[0])
                hour_moves[utc_hour].append(abs_move)

            t300_start = target_ms - 300_000
            idx_300 = int(np.searchsorted(ts_ms, t300_start, side="left"))
            n_300 = len(ts_ms) - idx_300
            if n_300 > 0:
                hour_spreads[utc_hour].append(float(np.mean(spread[idx_300:])))
                hour_rates[utc_hour].append(n_300 / 300.0)

        if progress_interval > 0 and count % progress_interval == 0:
            print(f"  [Baselines Pass 1] Processed {count:,} timestamps...")

    baselines = {}
    for h in range(24):
        moves = hour_moves[h]
        spreads = hour_spreads[h]
        rates = hour_rates[h]
        baselines[h] = {
            "abs_move_std": float(np.std(moves)) if len(moves) > 1 else 1.0,
            "spread_mean": float(np.mean(spreads)) if spreads else 1.0,
            "tick_rate_mean": float(np.mean(rates)) if rates else 1.0,
            "n_obs": len(moves),
        }

    return baselines


def extract_tick_features_streaming(
    store: TickStore,
    timestamps: Iterable[Union[str, int, pd.Timestamp]],
    baselines: Optional[dict] = None,
    batch_size: int = 10000,
    output_path: Optional[Union[Path, str]] = None,
    progress_interval: int = 50000,
) -> Union[dict, Path]:
    """
    Streaming extraction of 8 tick features across an iterable of timestamps.
    Maintains bounded memory by processing timestamps sequentially in batches,
    dropping raw tick DataFrames immediately after feature extraction.

    Parameters
    ----------
    store             : TickStore instance
    timestamps        : Iterable of timestamps to extract features for
    baselines         : Optional precomputed per-hour baselines dict
    batch_size        : Number of records to batch for Parquet writing
    output_path       : Optional path to write Parquet output
    progress_interval : Print progress every N timestamps (0 to disable)

    Returns
    -------
    dict mapping ts_str -> feature_dict (if output_path is None),
    or Path to the written Parquet file (if output_path is provided).
    """
    writer = None
    feature_schema = None
    if output_path is not None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        feature_schema = pa.schema([
            ("decision_time_utc", pa.string()),
            ("target_ms", pa.int64()),
            ("jump_z", pa.float64()),
            ("disp30", pa.float64()),
            ("tick_rate_30", pa.float64()),
            ("tick_rate_ratio", pa.float64()),
            ("spread_now", pa.float64()),
            ("spread_ratio", pa.float64()),
            ("ret5", pa.float64()),
            ("n_ticks_300", pa.float64()),
            ("tick_coverage", pa.float64()),
            ("utc_hour", pa.float64()),
            ("raw_abs_move_30", pa.float64()),
            ("raw_mean_spread_300", pa.float64()),
        ])
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(str(output_path), schema=feature_schema, compression="snappy")

    features_dict = {}
    batch_keys = []
    batch_target_ms = []
    batch_feats = []

    count = 0
    try:
        for ts in timestamps:
            count += 1
            if isinstance(ts, (int, np.integer)):
                target_ms = int(ts)
                ts_key = str(pd.Timestamp(target_ms, unit="ms"))
            elif isinstance(ts, pd.Timestamp):
                target_ms = int(ts.timestamp() * 1000)
                ts_key = str(ts.tz_localize(None) if ts.tzinfo else ts)
            else:
                ts_key = str(ts)
                target_ms = int(pd.Timestamp(ts_key).timestamp() * 1000)

            arrs = store.get_window_arrays(target_ms, lookback_sec=310.0)
            feats = extract_tick_features_arrays(arrs, target_ms, hour_baselines=baselines)

            if output_path is not None:
                batch_keys.append(ts_key)
                batch_target_ms.append(target_ms)
                batch_feats.append(feats)

                if len(batch_keys) >= batch_size:
                    batch_dict = {
                        "decision_time_utc": batch_keys,
                        "target_ms": batch_target_ms,
                        "jump_z": [f["jump_z"] for f in batch_feats],
                        "disp30": [f["disp30"] for f in batch_feats],
                        "tick_rate_30": [f["tick_rate_30"] for f in batch_feats],
                        "tick_rate_ratio": [f["tick_rate_ratio"] for f in batch_feats],
                        "spread_now": [f["spread_now"] for f in batch_feats],
                        "spread_ratio": [f["spread_ratio"] for f in batch_feats],
                        "ret5": [f["ret5"] for f in batch_feats],
                        "n_ticks_300": [f["n_ticks_300"] for f in batch_feats],
                        "tick_coverage": [f["tick_coverage"] for f in batch_feats],
                        "utc_hour": [f["utc_hour"] for f in batch_feats],
                        "raw_abs_move_30": [f["raw_abs_move_30"] for f in batch_feats],
                        "raw_mean_spread_300": [f["raw_mean_spread_300"] for f in batch_feats],
                    }
                    table = pa.Table.from_pydict(batch_dict, schema=feature_schema)
                    writer.write_table(table)
                    batch_keys.clear()
                    batch_target_ms.clear()
                    batch_feats.clear()
            else:
                features_dict[ts_key] = feats

            if progress_interval > 0 and count % progress_interval == 0:
                print(f"  [Features Pass 2] Processed {count:,} timestamps...")

        # Flush remaining batch
        if output_path is not None and len(batch_keys) > 0:
            batch_dict = {
                "decision_time_utc": batch_keys,
                "target_ms": batch_target_ms,
                "jump_z": [f["jump_z"] for f in batch_feats],
                "disp30": [f["disp30"] for f in batch_feats],
                "tick_rate_30": [f["tick_rate_30"] for f in batch_feats],
                "tick_rate_ratio": [f["tick_rate_ratio"] for f in batch_feats],
                "spread_now": [f["spread_now"] for f in batch_feats],
                "spread_ratio": [f["spread_ratio"] for f in batch_feats],
                "ret5": [f["ret5"] for f in batch_feats],
                "n_ticks_300": [f["n_ticks_300"] for f in batch_feats],
                "tick_coverage": [f["tick_coverage"] for f in batch_feats],
                "utc_hour": [f["utc_hour"] for f in batch_feats],
                "raw_abs_move_30": [f["raw_abs_move_30"] for f in batch_feats],
                "raw_mean_spread_300": [f["raw_mean_spread_300"] for f in batch_feats],
            }
            table = pa.Table.from_pydict(batch_dict, schema=feature_schema)
            writer.write_table(table)
            batch_keys.clear()
            batch_target_ms.clear()
            batch_feats.clear()

    finally:
        if writer is not None:
            writer.close()

    if output_path is not None:
        return output_path
    return features_dict


class IndexedTickControls:
    """
    Compact, indexed column-store for millions of tick feature rows loaded from Parquet.
    Provides dict-like .get(ts_str, default) access via O(log N) binary search on sorted target_ms
    without creating millions of heap dictionaries.
    """
    def __init__(self, parquet_path: Union[Path, str]):
        import pyarrow.parquet as pq
        table = pq.read_table(str(parquet_path))
        self.target_ms = table["target_ms"].to_numpy()
        self.column_names = [col for col in table.column_names if col not in ("target_ms", "decision_time_utc")]
        self.cols = {col: table[col].to_numpy() for col in self.column_names}

    def __len__(self) -> int:
        return len(self.target_ms)

    def get(self, dt_key: Union[str, int, pd.Timestamp], default=None) -> dict:
        if isinstance(dt_key, (int, np.integer)):
            target_ms = int(dt_key)
        elif isinstance(dt_key, pd.Timestamp):
            target_ms = int(dt_key.timestamp() * 1000)
        else:
            target_ms = int(pd.Timestamp(str(dt_key)).timestamp() * 1000)

        idx = int(np.searchsorted(self.target_ms, target_ms))
        if idx >= len(self.target_ms) or self.target_ms[idx] != target_ms:
            return default if default is not None else {}

        f_dict = {col: self.cols[col][idx] for col in self.column_names}
        return {"target_ms": target_ms, "features": f_dict}


if __name__ == "__main__":
    # Smoke test: load one tick file and extract features
    store = TickStore()
    # Trade 00983845: open_utc = 2026-09-18 03:25:04 UTC
    target = pd.Timestamp("2026-09-18 03:25:04", tz="UTC")
    target_ms = int(target.timestamp() * 1000)
    ticks = store.get_window(target_ms, lookback_sec=310.0, lookahead_sec=0.0)
    if ticks is not None:
        print(f"Ticks loaded: {len(ticks)} rows")
        print(f"ts_ms range: {ticks['ts_ms'].min()} to {ticks['ts_ms'].max()}")
        print(f"Target ms: {target_ms}")
        assert ticks["ts_ms"].max() < target_ms, "CAUSALITY VIOLATION: tick at or after target"
        feats = extract_tick_features(ticks, target_ms)
        print("\nFeatures:")
        for k, v in feats.items():
            print(f"  {k:20s}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
        print("\nSmoke test PASSED.")
    else:
        print("No ticks found for trade 00983845 entry window (check file: xauusd_ticks_2026-09-18T03-00-00-000Z.json)")
