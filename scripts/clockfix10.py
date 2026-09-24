"""
Phase 10/11 — Canonical Clock Correction Module
================================================
CRITICAL: Two different DST calendars apply to the two data sources:
  - Ledger timestamps (trades_raw.tsv / reconciliation CSV): recorded in broker local time.
    The broker follows US DST calendar:
      Spring forward: 2nd Sunday of March (2026-03-08, 2025-03-09)
      Fall back:      1st Sunday of November (2025-11-02, 2026-11-01)
    UTC offset: +2h (winter EET) / +3h (summer EEST per US calendar)

  - M1 market data (decision_panel.parquet): bar timestamps in UTC.
    No conversion needed — these are already UTC.

  - Raw tick data (xauusd_ticks_*.json): timestamps in milliseconds since epoch (UTC).
    No conversion needed.

DO NOT cross-apply calendars. This module handles ledger → UTC conversion only.
"""

from datetime import datetime, timezone, timedelta
import json
import pandas as pd
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# US DST Transition Calendar (for ledger timestamps)
# ─────────────────────────────────────────────────────────────────────────────
# Spring forward (2nd Sunday of March): clocks go +3h at 02:00 local
# Fall back    (1st Sunday of November): clocks go +2h at 03:00 local

_US_DST_TRANSITIONS = [
    # (spring_forward_utc, fall_back_utc)  — at the moment the offset changes
    # 2025: Spring = Mar 9 (2nd Sun),  Fall = Nov 2 (1st Sun)
    # 2026: Spring = Mar 8 (2nd Sun),  Fall = Nov 1 (1st Sun)
    (pd.Timestamp("2025-03-09 00:00:00", tz="UTC"), pd.Timestamp("2025-11-02 01:00:00", tz="UTC")),
    (pd.Timestamp("2026-03-08 00:00:00", tz="UTC"), pd.Timestamp("2026-11-01 01:00:00", tz="UTC")),
]
# In EET (UTC+2): spring occurs at 02:00 local = 00:00 UTC
# In EEST (UTC+3): fall   occurs at 03:00 local = 00:00 UTC (but broker = 01:00 UTC)
# We use approximate boundaries; exact second-of-transition is irrelevant for minute-level data.


def broker_local_to_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """
    Convert a broker-local naive timestamp (EET/EEST using US DST calendar)
    to UTC.

    Offset convention:
      - Winter (EET):  UTC+2  → UTC = local - 2h
      - Summer (EEST): UTC+3  → UTC = local - 3h

    US DST: spring forward 2nd Sunday March, fall back 1st Sunday November.

    Parameters
    ----------
    ts : pd.Timestamp (naive, broker local time)

    Returns
    -------
    pd.Timestamp (UTC, timezone-aware)
    """
    if ts.tzinfo is not None:
        raise ValueError(f"Expected naive timestamp, got tzinfo={ts.tzinfo}")

    # Determine DST offset by checking which period we're in
    # Strategy: assume winter (+2h), convert to tentative UTC, then check boundaries
    # The recorded time is ambiguous near transitions but minute-level data is fine
    year = ts.year
    transitions = None
    for sp, fb in _US_DST_TRANSITIONS:
        if sp.year == year:
            transitions = (sp, fb)
            break

    if transitions is None:
        # Default to winter UTC+2 for out-of-range years
        return (ts - timedelta(hours=2)).replace(tzinfo=timezone.utc)

    spring_utc, fall_utc = transitions

    # Try winter offset first (+2h → UTC = local - 2h)
    candidate_utc = ts - timedelta(hours=2)
    candidate_utc_ts = pd.Timestamp(candidate_utc, tz="UTC")

    if candidate_utc_ts < spring_utc or candidate_utc_ts >= fall_utc:
        # Winter period: offset is +2h
        return candidate_utc_ts
    else:
        # Summer period: offset is +3h → UTC = local - 3h
        summer_utc = ts - timedelta(hours=3)
        return pd.Timestamp(summer_utc, tz="UTC")


def broker_local_to_utc_series(s: pd.Series) -> pd.Series:
    """
    Vectorized conversion of broker-local timestamps to UTC.
    Applies US DST calendar (2nd Sunday March / 1st Sunday November).

    Parameters
    ----------
    s : pd.Series of naive datetime64 or Timestamp (broker local)

    Returns
    -------
    pd.Series of UTC datetime64[ns, UTC]
    """
    s = pd.to_datetime(s)

    result_utc = pd.Series(index=s.index, dtype="datetime64[ns, UTC]")

    for year in s.dt.year.unique():
        year_mask = s.dt.year == year
        year_ts = s[year_mask]

        transitions = None
        for sp, fb in _US_DST_TRANSITIONS:
            if sp.year == year:
                transitions = (sp, fb)
                break

        if transitions is None:
            # Winter +2h
            utc_vals = year_ts - pd.Timedelta(hours=2)
            result_utc[year_mask] = utc_vals.dt.tz_localize("UTC")
            continue

        spring_utc, fall_utc = transitions

        # Vectorized: try -2h first (winter), then check if in summer period
        candidate_w = year_ts - pd.Timedelta(hours=2)
        candidate_w_utc = candidate_w.dt.tz_localize("UTC")

        is_summer = (candidate_w_utc >= spring_utc) & (candidate_w_utc < fall_utc)

        winter_utc = candidate_w_utc
        summer_utc = (year_ts - pd.Timedelta(hours=3)).dt.tz_localize("UTC")

        combined = winter_utc.copy()
        combined[is_summer] = summer_utc[is_summer]
        result_utc[year_mask] = combined

    return result_utc


def load_trades_with_utc(trades_path: str) -> pd.DataFrame:
    """
    Load the canonical 423-trade ledger and add corrected UTC columns.

    Columns added:
      open_utc  : UTC datetime (US DST corrected)
      close_utc : UTC datetime (US DST corrected)
      open_utc_floor_min : open_utc floored to the minute (for M1 panel join)
    """
    df = pd.read_csv(
        trades_path,
        sep="\t",
        header=None,
        names=["row_id", "ticket", "side", "open_local", "close_local",
               "symbol", "volume", "price", "pnl"],
    )

    df["open_local"] = pd.to_datetime(df["open_local"])
    df["close_local"] = pd.to_datetime(df["close_local"])

    df["open_utc"] = broker_local_to_utc_series(df["open_local"])
    df["close_utc"] = broker_local_to_utc_series(df["close_local"])

    # Drop timezone for computation (keep as UTC-aware series for joins)
    df["open_utc_floor_min"] = df["open_utc"].dt.floor("min")

    # Sort chronologically
    df = df.sort_values("open_utc").reset_index(drop=True)
    df["trade_seq"] = range(len(df))  # 0-indexed chronological rank

    return df


def load_trades_from_recon(recon_path: str) -> pd.DataFrame:
    """
    Load from the phase7c reconciliation CSV which already has open_time_utc.
    These are pre-verified UTC timestamps; we use them directly.
    Returns DataFrame sorted chronologically with trade_seq column.
    """
    df = pd.read_csv(recon_path)
    df["open_utc"] = pd.to_datetime(df["open_time_utc"])
    df["close_utc"] = pd.to_datetime(df["close_time_utc"])
    df["open_utc"] = df["open_utc"].dt.tz_localize("UTC", ambiguous="NaT", nonexistent="NaT")
    df["close_utc"] = df["close_utc"].dt.tz_localize("UTC", ambiguous="NaT", nonexistent="NaT")

    # UTC-floor minute for M1 panel alignment
    df["open_utc_floor_min"] = df["open_utc"].dt.floor("min")

    df = df.sort_values("open_utc").reset_index(drop=True)
    df["trade_seq"] = range(len(df))

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Phase 10/11 decision-epoch layer
# ─────────────────────────────────────────────────────────────────────────────
# These are the only verified split-order executions.  Do not turn this into a
# generic proximity merger: the analysis contract collapses only these pairs.
SPLIT_ORDER_PAIRS = (
    ("36168589", "36168590"),  # Buy
    ("36227385", "36227388"),  # Sell
    ("36335183", "36335196"),  # Buy
)


def normalize_ticket(ticket: object) -> str:
    """Return a canonical ticket string without display-only leading zeroes."""
    value = str(ticket).strip()
    normalized = value.lstrip("0")
    return normalized or "0"


def build_decision_epochs(recon: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Derive the fixed Phase 10/11 decision-epoch representation.

    The first return value preserves all execution records and annotates their
    epoch membership.  The second contains one representative row per decision
    epoch.  Only ``SPLIT_ORDER_PAIRS`` are collapsed; every other record remains
    its own epoch.  The representative is always the earliest execution, so the
    tick decision cutoff never includes an earlier split execution.
    """
    required = {"ticket", "side", "open_utc", "close_utc"}
    missing = required.difference(recon.columns)
    if missing:
        raise ValueError(f"Cannot build decision epochs; missing columns: {sorted(missing)}")

    records = recon.copy()
    records["ticket_normalized"] = records["ticket"].map(normalize_ticket)
    records = records.sort_values(["open_utc", "close_utc", "ticket_normalized"], kind="mergesort").reset_index(drop=True)
    records["record_seq"] = np.arange(len(records), dtype=int)
    records["decision_epoch_utc"] = records["open_utc"].dt.floor("min")

    pair_by_ticket = {
        ticket: pair_index
        for pair_index, pair in enumerate(SPLIT_ORDER_PAIRS)
        for ticket in pair
    }
    found_tickets = set(records["ticket_normalized"])
    expected_tickets = set(pair_by_ticket)
    if not expected_tickets.issubset(found_tickets):
        absent = sorted(expected_tickets.difference(found_tickets))
        raise AssertionError(f"Verified split-order tickets missing from reconciliation: {absent}")

    pair_membership = records["ticket_normalized"].map(pair_by_ticket)
    records["split_pair_index"] = pair_membership
    records["is_split_order_member"] = pair_membership.notna()
    records["_epoch_key"] = [
        f"split:{int(pair_index)}" if pd.notna(pair_index) else f"record:{record_seq}"
        for pair_index, record_seq in zip(pair_membership, records["record_seq"])
    ]

    # Validate each hard-coded pair against canonical data before collapsing it.
    for pair_index, pair in enumerate(SPLIT_ORDER_PAIRS):
        members = records[records["split_pair_index"] == pair_index]
        if len(members) != 2 or set(members["ticket_normalized"]) != set(pair):
            raise AssertionError(f"Split-order pair {pair} does not have exactly its two members")
        if members["side"].nunique() != 1:
            raise AssertionError(f"Split-order pair {pair} has inconsistent directions")
        if members["decision_epoch_utc"].nunique() != 1:
            raise AssertionError(f"Split-order pair {pair} does not share one M1 decision minute")
        first, second = members.sort_values(["open_utc", "close_utc", "ticket_normalized"], kind="mergesort").iloc[:2].itertuples()
        if not (first.open_utc < second.open_utc < first.close_utc):
            raise AssertionError(f"Split-order pair {pair} is not strictly overlapping")

    first_record_order = records.groupby("_epoch_key", sort=False)["record_seq"].min().sort_values()
    epoch_id_by_key = {key: epoch_id for epoch_id, key in enumerate(first_record_order.index)}
    records["epoch_id"] = records["_epoch_key"].map(epoch_id_by_key).astype(int)
    records["epoch_record_count"] = records.groupby("epoch_id")["epoch_id"].transform("size").astype(int)
    records["epoch_record_rank"] = records.groupby("epoch_id").cumcount().astype(int)
    records["is_epoch_anchor"] = records["epoch_record_rank"].eq(0)
    records["representative_ticket"] = records.groupby("epoch_id")["ticket_normalized"].transform("first")
    records["decision_time_utc"] = records.groupby("epoch_id")["open_utc"].transform("first")

    # Strict overlap is a record-level execution diagnostic, not an epoch rule.
    active_counts = []
    for row in records.itertuples():
        active_counts.append(int(((records["open_utc"] < row.open_utc) & (records["close_utc"] > row.open_utc)).sum()))
    records["active_positions_before_entry"] = active_counts
    records["entry_while_position_active"] = records["active_positions_before_entry"].gt(0)

    epoch_rows = []
    for epoch_id, members in records.groupby("epoch_id", sort=True):
        members = members.sort_values("epoch_record_rank", kind="mergesort")
        anchor = members.iloc[0]
        epoch_rows.append({
            "epoch_id": int(epoch_id),
            "decision_epoch_utc": anchor["decision_epoch_utc"],
            "decision_time_utc": anchor["decision_time_utc"],
            "anchor_open_utc": anchor["open_utc"],
            "anchor_ticket": anchor["ticket_normalized"],
            "side": anchor["side"],
            "record_count": int(len(members)),
            "tickets": json.dumps(members["ticket_normalized"].tolist()),
            "record_seqs": json.dumps([int(v) for v in members["record_seq"]]),
            "sides": json.dumps(members["side"].astype(str).tolist()),
            "volumes": json.dumps([float(v) for v in members["volume"]]) if "volume" in members else "[]",
            "is_concurrent_epoch": bool(len(members) > 1),
            "strict_overlap_count": int(members["entry_while_position_active"].sum()),
        })
    epochs = pd.DataFrame(epoch_rows)

    if len(records) != 423:
        raise AssertionError(f"Expected 423 execution records, got {len(records)}")
    if len(epochs) != 420:
        raise AssertionError(f"Expected 420 decision epochs, got {len(epochs)}")
    if int((epochs["record_count"] == 2).sum()) != 3 or int((epochs["record_count"] > 2).sum()) != 0:
        raise AssertionError("Expected exactly three two-record decision epochs")
    if int(records["entry_while_position_active"].sum()) != 3:
        raise AssertionError("Expected exactly three strictly overlapping later entries")
    if records["decision_epoch_utc"].nunique() != 420:
        raise AssertionError("M1 decision-minute count must equal 420")

    return records.drop(columns=["_epoch_key"]), epochs


# ─────────────────────────────────────────────────────────────────────────────
# EU DST Transition Calendar (for M1 market data, for reference only)
# ─────────────────────────────────────────────────────────────────────────────
# M1 bars are already in UTC — no conversion needed.
# If ever checking EET/EEST labels on M1 bar times, apply these transitions:
#   Spring: last Sunday of March    (2025-03-30, 2026-03-29)
#   Fall:   last Sunday of October  (2025-10-26, 2026-10-25)
# DO NOT apply EU DST transitions to ledger timestamps.

_EU_DST_TRANSITIONS = [
    (pd.Timestamp("2025-03-30 00:00:00", tz="UTC"), pd.Timestamp("2025-10-26 01:00:00", tz="UTC")),
    (pd.Timestamp("2026-03-29 00:00:00", tz="UTC"), pd.Timestamp("2026-10-25 01:00:00", tz="UTC")),
]


def utc_to_eet_label(utc_ts: pd.Timestamp) -> str:
    """Return 'EET' or 'EEST' for a given UTC timestamp, using EU DST calendar."""
    if utc_ts.tzinfo is None:
        utc_ts = utc_ts.tz_localize("UTC")
    year = utc_ts.year
    for sp, fb in _EU_DST_TRANSITIONS:
        if sp.year == year:
            if sp <= utc_ts < fb:
                return "EEST(EU+3)"
            else:
                return "EET(EU+2)"
    return "EET(EU+2)"


if __name__ == "__main__":
    # Smoke test: verify a known trade conversion
    # Trade 00983845: recorded open 2026-09-18T06:25:04 (broker local EEST +3h)
    #                 expected UTC: 2026-09-18T03:25:04
    t_local = pd.Timestamp("2026-09-18 06:25:04")
    t_utc = broker_local_to_utc(t_local)
    print(f"Local: {t_local} -> UTC: {t_utc}")
    assert str(t_utc) == "2026-09-18 03:25:04+00:00", f"Mismatch: {t_utc}"

    # Trade 100829495: recorded open 2026-09-17T16:21:20 -> UTC 13:21:20
    t_local2 = pd.Timestamp("2026-09-17 16:21:20")
    t_utc2 = broker_local_to_utc(t_local2)
    print(f"Local: {t_local2} -> UTC: {t_utc2}")
    assert str(t_utc2) == "2026-09-17 13:21:20+00:00", f"Mismatch: {t_utc2}"

    print("Smoke test PASSED: Clock conversion correct.")
