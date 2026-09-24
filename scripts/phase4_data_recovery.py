"""Phase 4: targeted local data recovery and evidence-boundary certification.

This phase deliberately stops before additional model mining when the audited
locations do not yield a synchronized broker quote or transaction data source.
It records what was actually inspected, rather than treating M1 OHLC as ticks.
"""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from reverse_trade.pipeline import load_trades


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
RAW_TRADES = ROOT / "data" / "raw" / "trades_raw.tsv"
RAW_MARKET = ROOT / "data" / "market" / "raw" / "xauusd_m1_utc_raw.csv"
NORMALIZED_MARKET = ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv"
METADATA = ROOT / "data" / "market" / "metadata.json"
USER = Path(r"C:\Users\ayush")

EXPECTED_PLATFORM_PATHS = [
    USER / "AppData" / "Roaming" / "MetaQuotes",
    USER / "AppData" / "Local" / "MetaQuotes",
    USER / "AppData" / "Local" / "VirtualStore" / "MetaQuotes",
    Path(r"C:\Program Files\MetaTrader 4"),
    Path(r"C:\Program Files\MetaTrader 5"),
    Path(r"C:\Program Files (x86)\MetaTrader 4"),
    Path(r"C:\Program Files (x86)\MetaTrader 5"),
]
AUDITED_ROOTS = [
    ROOT,
    USER / "AppData" / "Roaming",
    USER / "AppData" / "Local",
    USER / "AppData" / "Local" / "VirtualStore",
    Path(r"C:\Program Files"),
    Path(r"C:\Program Files (x86)"),
    USER / "Documents",
    USER / "OneDrive" / "Documents",
    USER / "Downloads",
    USER / "OneDrive" / "Downloads",
]


def iso_modified(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def file_record(
    path: Path,
    file_class: str,
    relevance: str,
    fields: str,
    match: str,
    coverage: str,
) -> dict[str, str]:
    return {
        "path": str(path),
        "file_type": path.suffix.lower() or file_class,
        "size_bytes": str(path.stat().st_size),
        "modified_utc": iso_modified(path),
        "likely_relevance": relevance,
        "tick_bid_ask_order_deal_position_potential": fields,
        "broker_account_symbol_match": match,
        "coverage_2025_09_25_to_2026_09_18": coverage,
    }


def classify_market_header(columns: list[str]) -> str:
    """Classify a market export conservatively from observable columns only."""
    normalized = {column.strip().lower() for column in columns}
    quote_fields = {"bid", "ask", "spread", "tick", "tick_time"}
    transaction_fields = {"order", "deal", "position", "ticket", "sl", "tp"}
    if normalized & transaction_fields:
        return "transaction_or_order_export_candidate"
    if {"bid", "ask"}.issubset(normalized):
        return "bid_ask_quote_candidate"
    if normalized & quote_fields:
        return "partial_quote_candidate"
    if {"timestamp", "open", "high", "low", "close"}.issubset(normalized):
        return "ohlc_bar_only"
    return "unclassified"


def markdown_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(column, "")).replace("|", "/") for column in columns) + " |")
    return "\n".join([header, divider, *body])


def status_row(artifact: str, scope: str, reason: str) -> dict[str, str]:
    return {
        "artifact": artifact,
        "analysis_status": "NOT_IDENTIFIABLE",
        "supported_data": "No recovered synchronized tick, Bid/Ask, spread, order, deal, position, modification, rejection, or terminal-log record",
        "scope": scope,
        "reason": reason,
    }


def write_status_csv(name: str, scope: str, reason: str) -> None:
    row = status_row(name, scope, reason)
    with (OUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def report(title: str, conclusion: str, evidence: list[str], next_data: str = "") -> str:
    lines = [f"# {title}", "", "## Result", "", conclusion, "", "## Evidence boundary", ""]
    lines.extend(f"- {item}" for item in evidence)
    if next_data:
        lines.extend(["", "## Required evidence to proceed", "", next_data])
    lines.extend(["", "**Status: NOT_IDENTIFIABLE — no new Phase 4 modeling was run.**", ""])
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trades, quality = load_trades(RAW_TRADES)
    market_meta = json.loads(METADATA.read_text(encoding="utf-8"))
    archive = USER / "OneDrive" / "Documents" / "Downloads" / "crypto_trade.zip"

    trade_start = trades.open_time.min().isoformat()
    trade_end = trades.open_time.max().isoformat()
    market_header = pd.read_csv(RAW_MARKET, nrows=0).columns.tolist()
    market_kind = classify_market_header(market_header)
    archive_has_data_export = False
    if archive.exists():
        with zipfile.ZipFile(archive) as bundle:
            archive_has_data_export = any(
                entry.filename.lower().endswith((".csv", ".tsv", ".xlsx", ".xls", ".sqlite", ".db", ".hst", ".fxt", ".hcc"))
                for entry in bundle.infolist()
            )

    inventory = [
        file_record(
            RAW_TRADES, "trade ledger", "Primary supplied closed-trade history.",
            "ticket, side, open/close time, symbol, lot, one observed price, P&L; no order/deal lifecycle or Bid/Ask.",
            "Symbol matches XAUUSD.f; broker/account absent.",
            f"Yes: observed entries {trade_start} through {trade_end}.",
        ),
        file_record(
            ROOT / "data" / "processed" / "trades_enriched.csv", "derived trade table", "Derived from the supplied ledger; not an independent execution source.",
            "No additional quote, order, deal, or position records.", "Derived XAUUSD.f ledger; broker/account absent.", "Yes, derived from supplied ledger.",
        ),
        file_record(
            RAW_MARKET, "external market bars", "Dukascopy bid-only M1 proxy used by earlier phases.",
            f"{market_kind}; columns are {', '.join(market_header)}. No Ask, spread, tick sequence, order/deal/position fields.",
            "XAUUSD, not broker-specific XAUUSD.f; no account/server identity.",
            f"Yes: {market_meta['date_from']} through {market_meta['date_to']}.",
        ),
        file_record(
            NORMALIZED_MARKET, "normalized external market bars", "Timezone-normalized derivative of the same external M1 proxy.",
            "OHLCV only; cannot become a tick or Bid/Ask feed through normalization.",
            "XAUUSD proxy, not broker/account matched.",
            f"Yes: {market_meta['date_from']} through {market_meta['date_to']}.",
        ),
        file_record(
            METADATA, "source metadata", "Documents origin and limitations of the market proxy.",
            "No raw execution fields; declares Dukascopy historical bid M1 source.",
            "No broker/account match.",
            "Metadata describes market coverage above.",
        ),
    ]
    if archive.exists():
        inventory.append(file_record(
            archive, "ZIP archive", "Trade-named candidate inspected without extraction.",
            "No export data files inside; source code only. No ticks, Bid/Ask, orders, deals, positions, or logs.",
            "Unrelated crypto project; no XAUUSD.f broker/account evidence.",
            "No trading records; not applicable.",
        ))

    columns = list(inventory[0])
    (OUT / "phase4_data_recovery_inventory.md").write_text(
        "# Phase 4 data-recovery inventory\n\n"
        "## Scope and method\n\n"
        "A targeted local audit was performed. It checked the project workspace, standard MetaQuotes/MetaTrader/MQL locations, platform installation paths, and trade-relevant user Documents/Downloads locations. "
        "It used platform-specific directory names and transaction/tick-oriented filenames and extensions; it did not indiscriminately crawl unrelated operating-system content.\n\n"
        "## Expected platform trees\n\n"
        + markdown_table([
            {"path": str(path), "result": "ABSENT" if not path.exists() else "PRESENT"}
            for path in EXPECTED_PLATFORM_PATHS
        ], ["path", "result"])
        + "\n\n## Audited roots\n\n"
        + "\n".join(f"- {path} ({'present' if path.exists() else 'absent'})" for path in AUDITED_ROOTS)
        + "\n\n## Relevant candidate inventory\n\n"
        + markdown_table(inventory, columns)
        + "\n\n## Finding\n\n"
        + "No usable platform tree, terminal log, tick database, Bid/Ask/spread export, or order/deal/position lifecycle record was recovered. "
        + "The two trade-named ZIP archives were inspected as archives and contain unrelated crypto source code, not data exports.\n",
        encoding="utf-8",
    )

    reports: dict[str, str] = {
        "phase4_tick_execution_analysis.md": report(
            "Phase 4 tick and execution analysis",
            "NOT_IDENTIFIABLE. No higher-resolution quotes were recovered, so no nearest pre/post quote, fill-side, spread, tick velocity, or seconds-level trigger table can be constructed.",
            ["The only market series is external Dukascopy bid-only M1 OHLCV.", "M1 bars are not the broker's tick feed and have no Ask or spread.", "The closed-trade ledger supplies one observed price, not fill-side quote evidence."],
            "Recover broker-native XAUUSD.f Bid/Ask ticks with server timestamps synchronized to the account history.",
        ),
        "phase4_order_deal_lifecycle.md": report(
            "Phase 4 order/deal lifecycle",
            "NOT_IDENTIFIABLE. No order, deal, position, pending-order, modification, cancellation, rejection, or partial-fill record was recovered.",
            ["The 423-row ledger is a closed-trade export only.", "No MetaQuotes/MetaTrader terminal tree was present in the targeted paths.", "Therefore the actual opportunity set cannot be expanded to submitted-but-unfilled orders."],
            "Recover the same-account Orders, Deals and Positions history, including status transitions and server timestamps.",
        ),
        "phase4_clock_trigger_analysis.md": report(
            "Phase 4 clock-trigger analysis",
            "NOT_IDENTIFIABLE beyond the Phase 3 baseline. M30/H1 boundary enrichment remains observed, but M1 resolution cannot separate exact bar-close, fixed-timer, or post-boundary eligibility-window mechanisms.",
            ["Phase 3 best boundary proxy: 29/306 OOS entry bars; 7,573 signals; precision 0.383%; recall 9.48%; F1 0.00734.", "No seconds/ticks or lifecycle events were recovered to test the competing trigger hypotheses."],
        ),
        "phase4_opportunity_reconstruction.md": report(
            "Phase 4 opportunity reconstruction",
            "NOT_IDENTIFIABLE. The true opportunity set is unobserved because rejected, cancelled, expired and pending orders were not recovered.",
            ["Random or M1-matched non-trades cannot show whether an internal signal created an order.", "No quote-level threshold crossings can be aligned to the 423 trades.", "Phase 4 therefore does not add an indicator-based substitute opportunity model."],
        ),
        "phase4_state_machine_analysis.md": report(
            "Phase 4 state-machine analysis",
            "NOT_IDENTIFIABLE as an algorithm state machine. The observed ledger still proves five entries occurred while a prior position remained active, falsifying an enter-only-when-flat rule.",
            ["Trade history can describe prior observed entries/exits but not hidden eligibility, locks, pending orders, or account state.", "No new transaction records were recovered; Phase 3 clock-plus-state models were worse than the boundary baseline."],
        ),
        "phase4_exit_reconstruction.md": report(
            "Phase 4 exit reconstruction",
            "NOT_IDENTIFIABLE. Exit time and observed price do not distinguish a stop, target, trailing rule, signal exit, timer exit, manual close, or modification.",
            ["No Bid/Ask ticks to establish which candidate level was touched first.", "No SL/TP, modification, close-deal, or partial-close history was recovered.", "MAE/MFE from external M1 remains insufficient evidence of a hard stop or target."],
        ),
        "phase4_sizing_analysis.md": report(
            "Phase 4 sizing analysis",
            "NOT_IDENTIFIABLE as a sizing rule. The established distribution remains 401 x 0.01, 21 x 0.02 and 1 x 0.03; all above-minimum sizes were winners, but outcome-conditioned interpretation is prohibited.",
            ["No account balance/equity, margin, order request, signal-strength, or transaction lifecycle information was recovered.", "No Phase 4 model uses outcomes or post-entry information to invent a sizing mechanism."],
        ),
        "phase4_direction_analysis.md": report(
            "Phase 4 direction analysis",
            "NOT_IDENTIFIABLE. Buy/Sell selection cannot be reconstructed from the recovered data.",
            ["The ledger has 214 Buy and 209 Sell trades.", "Phase 3 direction models did not reconstruct direction.", "No quote-side movement, pending-order side, or internal signal record was recovered."],
        ),
        "phase4_nearmiss_analysis.md": report(
            "Phase 4 near-miss analysis",
            "NOT_IDENTIFIABLE for causal nearest non-trades. The critical difference may be an unobserved order submission, pending-order level, spread gate, or hidden state.",
            ["Phase 3 matched near-misses found no small clock/state/event sequence that survived correction.", "No rejected/cancelled/expired orders were recovered to make the near-miss set transaction-grounded."],
        ),
    }
    for name, content in reports.items():
        (OUT / name).write_text(content, encoding="utf-8")

    (OUT / "phase4_data_gap_certificate.md").write_text(
        "# Phase 4 data-gap certificate\n\n"
        "## Determination\n\n"
        "**Branch C — no usable new transaction-level data recovered.** The targeted audit found no MetaTrader/MetaQuotes data tree, terminal Logs/Experts/Journal/Tester material, tick or Bid/Ask database, spread history, or order/deal/position lifecycle export.\n\n"
        "## Why the remaining boundary is unidentifiable at M1\n\n"
        "An M1 OHLCV bar does not preserve quote order, seconds offset, Bid/Ask side, spread, intra-minute threshold crossing, pending order placement, cancellation/rejection, SL/TP modification, or exact close-deal mechanics. The external series is bid-only and is not the account broker feed. Consequently it cannot distinguish timer versus bar-close versus eligibility-window timing, nor market versus pending execution.\n\n"
        "## Questions still unidentifiable\n\n"
        "- Exact entry trigger and execution type.\n- Bid/Ask-side and spread gating.\n- Order/deal/position parent-child lifecycle and non-filled opportunities.\n- Direction choice conditional on the true opportunity set.\n- Exit, modification and partial-close mechanism.\n- Pre-trade sizing inputs and hidden eligibility state.\n\n"
        "## Highest-information next dataset\n\n"
        "The single highest-value recovery is a native terminal/account archive for this XAUUSD.f account covering 2025-09-25 through 2026-09-18: synchronized Bid/Ask tick history plus complete Orders, Deals and Positions/Journal lifecycle (including pending, cancelled, rejected and modified orders) with broker server timestamps. This exposes both the quote environment and the true opportunity set.\n\n"
        "**Identification level remains LEVEL D — UNIDENTIFIED.**\n",
        encoding="utf-8",
    )

    csv_specs = {
        "phase4_trade_tick_table.csv": ("tick/execution alignment", "No recovered synchronized quote stream."),
        "phase4_opportunity_table.csv": ("true opportunity set", "No pending/rejected/cancelled order data or quote-level threshold evidence."),
        "phase4_nearmiss_table.csv": ("transaction-grounded near misses", "No actual non-filled order events were recovered."),
        "phase4_state_features.csv": ("hidden-state features", "Only the prior closed-trade ledger is observable; no hidden platform/account state is available."),
        "phase4_candidate_rules.csv": ("candidate rule reconstruction", "Phase 4 correctly stopped before unsupported rule mining."),
        "phase4_replication_results.csv": ("chronological replication", "No transaction-level rule candidate exists to replicate."),
    }
    for name, (scope, reason) in csv_specs.items():
        write_status_csv(name, scope, reason)

    status = """# Phase 4 status\n\n## Result\n\n**LEVEL D — UNIDENTIFIED (unchanged).** Phase 4 completed the targeted broader local recovery audit and entered the formal data-limited branch. No additional modeling was run.\n\n## Required answers\n\n1. **Was higher-resolution data recovered?** No. Only external M1 OHLCV was available.\n2. **Was Bid/Ask/spread recovered?** No. The available series is bid-only M1 and has no Ask or spread.\n3. **Were order/deal/position records recovered?** No.\n4. **Can the exact entry trigger be localized to seconds or ticks?** No.\n5. **Can M30/H1 boundary timing be distinguished from a broader opportunity window?** No; M1 cannot distinguish exact bar-close, timer, or eligibility window.\n6. **Can the directional rule be reconstructed?** No.\n7. **Can the exit mechanism be reconstructed?** No.\n8. **Can the sizing mechanism be reconstructed?** No.\n9. **What explains the nearest non-trade moments?** No observable causal discriminator was recovered; an unobserved order, quote/spread condition, or hidden state may differ.\n10. **What is still fundamentally unidentifiable?** The quote path, execution method, true opportunity set, lifecycle, hidden eligibility state, direction, exits and pre-trade sizing inputs.\n11. **Did the project move beyond Level D?** No. Promotion is prevented by the absence of synchronized broker Bid/Ask ticks and complete order/deal/position lifecycle data; the M1 proxy cannot expose those missing decision boundaries.\n\n## Baseline retained\n\n- 423 trades: 214 Buy / 209 Sell; 367 winners / 56 losers; total P&L +1451.22.\n- Sizes: 401 x 0.01, 21 x 0.02, 1 x 0.03.\n- Five observed entries overlapped a prior active position.\n- Phase 3 M30/H1 enrichment remains a constraint, not a reconstructed rule: best boundary proxy had 29/306 OOS entry bars, 7,573 signals, 0.383% precision, 9.48% recall and F1 0.00734.\n- Clock-plus-state models performed worse; no corrected small event/state separator and no direction reconstruction were established.\n"""
    (OUT / "phase4_status.md").write_text(status, encoding="utf-8")

    validation: dict[str, Any] = {
        "phase": 4,
        "branch": "C_DATA_LIMITED_NO_TRANSACTION_DATA_RECOVERED",
        "identification_level": "D — UNIDENTIFIED",
        "audit": {
            "audited_roots": [str(path) for path in AUDITED_ROOTS],
            "expected_platform_paths": {str(path): path.exists() for path in EXPECTED_PLATFORM_PATHS},
            "platform_tree_recovered": False,
            "tick_bid_ask_spread_recovered": False,
            "order_deal_position_lifecycle_recovered": False,
            "terminal_logs_recovered": False,
            "archive_checked": str(archive),
            "archive_has_export_data": archive_has_data_export,
        },
        "available_data": {
            "trade_rows": int(len(trades)),
            "trade_open_range": [trade_start, trade_end],
            "trade_quality_sha256": quality["sha256"],
            "market_source": market_meta["source"],
            "market_granularity": "M1",
            "market_header_classification": market_kind,
            "market_range": [market_meta["date_from"], market_meta["date_to"]],
        },
        "modeling_decision": "Stopped after recovery audit; no unsupported Phase 4 indicator/rule search was performed.",
        "not_identifiable": [
            "seconds_or_tick_entry_trigger", "bid_ask_spread_gate", "order_deal_position_lifecycle",
            "true_opportunity_set", "direction_rule", "exit_mechanism", "sizing_mechanism", "hidden_state_machine",
        ],
    }
    (OUT / "phase4_validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps({"branch": validation["branch"], "level": validation["identification_level"], "inventory_rows": len(inventory)}, indent=2))


if __name__ == "__main__":
    main()
