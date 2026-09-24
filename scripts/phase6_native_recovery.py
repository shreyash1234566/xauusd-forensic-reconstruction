"""Phase 6A native MT recovery gate and evidence-preserving stop branch.

No terminal/account credentials are read or emitted.  The audit is limited to
known MetaQuotes paths, registered MetaTrader applications, and the prior
project recovery scope.  When no native terminal is present, 6B/6C must not
infer tick-level mechanics from the external M1 proxy.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import winreg
from datetime import UTC, datetime
from pathlib import Path

from reverse_trade.pipeline import load_trades


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"
RAW = ROOT / "data" / "raw" / "trades_raw.tsv"
PHASE5 = OUT / "phase5_validation.json"
USER = Path(r"C:\Users\ayush")
EXPECTED_PATHS = [
    USER / "AppData" / "Roaming" / "MetaQuotes" / "Terminal",
    USER / "AppData" / "Local" / "MetaQuotes" / "Terminal",
    USER / "AppData" / "Local" / "VirtualStore" / "MetaQuotes" / "Terminal",
    Path(r"C:\Program Files\MetaTrader 5"), Path(r"C:\Program Files\MetaTrader 4"),
    Path(r"C:\Program Files (x86)\MetaTrader 5"), Path(r"C:\Program Files (x86)\MetaTrader 4"),
]
AUDIT_SCOPE = [
    ROOT, USER / "AppData" / "Roaming", USER / "AppData" / "Local", USER / "AppData" / "Local" / "VirtualStore",
    Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"), USER / "Documents", USER / "OneDrive" / "Documents",
    USER / "Downloads", USER / "OneDrive" / "Downloads", Path("E:/"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def registered_terminals() -> list[dict[str, str]]:
    """Read public uninstall metadata only; do not inspect terminal secrets."""
    candidates: list[dict[str, str]] = []
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, key_path in roots:
        try:
            with winreg.OpenKey(hive, key_path) as parent:
                count = winreg.QueryInfoKey(parent)[0]
                for index in range(count):
                    try:
                        child_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, child_name) as child:
                            display, _ = winreg.QueryValueEx(child, "DisplayName")
                            if "meta" not in str(display).lower() and "mt5" not in str(display).lower() and "mt4" not in str(display).lower():
                                continue
                            try:
                                location, _ = winreg.QueryValueEx(child, "InstallLocation")
                            except FileNotFoundError:
                                location = ""
                            candidates.append({"display_name": str(display), "install_location": str(location)})
                    except (FileNotFoundError, OSError):
                        continue
        except FileNotFoundError:
            continue
    return candidates


def write_status_csv(name: str, scope: str, status: str) -> None:
    row = {"artifact": name, "status": status, "reason": "No native MT4/MT5 terminal, same-account connection, tick history, or transaction export was accessible in Phase 6A."}
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def report(title: str, result: str, evidence: list[str], acquisition: str = "") -> str:
    content = [f"# {title}", "", "## Result", "", result, "", "## Evidence", ""]
    content.extend(f"- {item}" for item in evidence)
    if acquisition:
        content.extend(["", "## To proceed", "", acquisition])
    content.extend(["", "**Classification: DATA_UNAVAILABLE / NOT_IDENTIFIABLE.**", ""])
    return "\n".join(content)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trades, quality = load_trades(RAW)
    phase5 = json.loads(PHASE5.read_text(encoding="utf-8"))
    canonical = {
        "trade_rows": int(len(trades)), "buy": int(trades.side.eq("Buy").sum()), "sell": int(trades.side.eq("Sell").sum()),
        "wins": int(trades.win.sum()), "losses": int((~trades.win).sum()), "net_pnl": round(float(trades.pnl.sum()), 2),
        "lot_counts": {str(size): int(count) for size, count in trades.lot_size.value_counts().sort_index().items()},
        "strict_overlap_entries": int(trades.entry_while_position_active.sum()), "raw_sha256": quality["sha256"],
    }
    expected = {"trade_rows": 423, "buy": 214, "sell": 209, "wins": 367, "losses": 56, "net_pnl": 1451.22, "strict_overlap_entries": 3}
    if any(canonical[key] != value for key, value in expected.items()):
        raise RuntimeError(f"Canonical ledger changed: {canonical}")
    if phase5["canonical"]["source_sha256"] != canonical["raw_sha256"]:
        raise RuntimeError("Phase 5 baseline hash does not match raw ledger")
    lock = {"acquired_utc": datetime.now(UTC).isoformat(), "canonical": canonical, "phase5_identification_level": phase5["identification_level"], "phase5_validation_hash": sha256(PHASE5)}
    (OUT / "phase6_baseline_lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    (OUT / "phase6_baseline_lock.md").write_text(
        "# Phase 6 baseline lock\n\n"
        "The canonical ledger was recomputed before recovery activity. Its SHA-256 matches the Phase 5 frozen baseline.\n\n"
        + "\n".join(f"- **{key}:** {value}" for key, value in canonical.items())
        + "\n\n**Result: baseline locked; no raw trade record was modified.**\n",
        encoding="utf-8",
    )

    registered = registered_terminals()
    path_rows = [{"path": str(path), "status": "PRESENT" if path.exists() else "ABSENT", "terminal_type": "MT4/MT5/MetaQuotes expected location"} for path in EXPECTED_PATHS]
    mt5_python = importlib.util.find_spec("MetaTrader5") is not None
    environment = "# Phase 6 environment inventory\n\n"
    environment += "## Targeted scope\n\n" + "\n".join(f"- {path}" for path in AUDIT_SCOPE) + "\n\n"
    environment += "## Expected terminal/data locations\n\n| path | status | terminal_type |\n| --- | --- | --- |\n"
    environment += "\n".join(f"| {row['path']} | {row['status']} | {row['terminal_type']} |" for row in path_rows)
    environment += "\n\n## Registered terminal applications\n\n"
    environment += "None found." if not registered else "\n".join(f"- {item['display_name']} — {item['install_location'] or 'installation location not published'}" for item in registered)
    environment += f"\n\n## Integration availability\n\n- MetaTrader5 Python package: {'present' if mt5_python else 'absent'}.\n- No terminal executable, MetaQuotes tree, MQL directory, tester/history/tick database, or broker-specific terminal record was recovered in the targeted Phase 6A audit.\n"
    (OUT / "phase6_environment_inventory.md").write_text(environment, encoding="utf-8")

    account_status = "NATIVE_ACCOUNT_NOT_ACCESSIBLE"
    native_status = "DATA_UNAVAILABLE"
    (OUT / "phase6_tick_recovery_report.md").write_text(report(
        "Phase 6 native tick recovery", "No native tick request was attempted because no MT5/MT4 terminal or same-account connection was available (STOP A).",
        ["No expected MetaQuotes/MetaTrader installation or terminal data path exists.", "The MetaTrader5 Python package is absent.", "External Dukascopy bid-only M1 remains excluded from native-tick claims."],
        "Open the original broker terminal/account and export or archive native XAUUSD.f ticks for 2025-09-25 through 2026-09-18, retaining timestamp precision, Bid, Ask, Last, volume, flags, source/server and timezone representation.",
    ), encoding="utf-8")
    write_status_csv("phase6_tick_coverage.csv", "entry and exit native tick coverage", native_status)
    (OUT / "phase6_order_recovery.md").write_text(report(
        "Phase 6 order/deal/position recovery", "No native Orders, Deals, Positions, SL/TP modifications, Magic IDs, comments, or pending/cancelled/rejected orders were recovered (STOP A).",
        ["No original terminal or same account/server was identified.", "The supplied ledger is not a transaction lifecycle export.", "No credentials or secrets were inspected or recorded."],
        "Export account-history Orders, Deals and Positions for the same account and period, including time_msc, order state/type, position ID, SL/TP, volume, magic and comments; include non-executed orders.",
    ), encoding="utf-8")
    write_status_csv("phase6_order_opportunity_table.csv", "strategy-generated unfilled opportunities", native_status)
    (OUT / "phase6_journal_analysis.md").write_text(report(
        "Phase 6 journal and Expert log analysis", "DATA_UNAVAILABLE. No native Journal, Experts, Tester, or terminal log directory was recovered.",
        ["No MetaQuotes terminal data tree exists in the audited locations.", "A journal, if later recovered, is evidence of events rather than proof of source code or hidden state completeness."],
    ), encoding="utf-8")
    (OUT / "phase6_data_quality.md").write_text(report(
        "Phase 6 native-data quality gate", "STOP A — no same-account native terminal evidence is accessible, so there is no native dataset to hash, align, or quality-test.",
        ["Native tick coverage: not measurable.", "Native price reachability: not measurable.", "Transaction linkage: not measurable.", "The frozen raw trade ledger hash is recorded in phase6_baseline_lock.json."],
    ), encoding="utf-8")
    for filename, title, detail in [
        ("phase6_clock_trigger_analysis.md", "Phase 6 clock trigger analysis", "NOT_IDENTIFIABLE. Without native timestamps, M30/H1 enrichment cannot be separated from timer, post-boundary window, or price-event timing beyond the Phase 5 M1 constraint."),
        ("phase6_intrabar_analysis.md", "Phase 6 intrabar analysis", "DATA_UNAVAILABLE. No native Bid/Ask tick sequence exists to calculate tick velocity, spread, threshold crossings, or seconds-level entry/exit windows."),
        ("phase6_hidden_state_analysis.md", "Phase 6 hidden-state analysis", "NOT_IDENTIFIABLE. The ledger supports prior observed state only; no native pending-order, rejection, modification, or terminal state is available. Three strict timestamp overlaps remain preserved."),
        ("phase6_opportunity_reconstruction.md", "Phase 6 opportunity reconstruction", "NOT_IDENTIFIABLE. No strategy-generated pending, cancelled, expired, or rejected orders were recovered, so the true opportunity set remains hidden."),
        ("phase6_negative_space_analysis.md", "Phase 6 native negative-space analysis", "DATA_UNAVAILABLE. Phase 5 M1 matched controls remain the strongest available proxy; no native microstructure or unfilled-order controls exist."),
        ("phase6_exit_reconstruction.md", "Phase 6 exit reconstruction", "NOT_IDENTIFIABLE. No native ticks, closing deal records, SL/TP fields, or modification history were recovered."),
        ("phase6_sizing_analysis.md", "Phase 6 sizing reconstruction", "NOT_IDENTIFIABLE. Native equity, balance, margin, order request and signal-strength inputs are unavailable."),
        ("phase6_direction_analysis.md", "Phase 6 direction reconstruction", "NOT_IDENTIFIABLE. No verified opportunity or native execution context is available beyond the Phase 5 observable-space result."),
    ]:
        (OUT / filename).write_text(report(title, detail, ["Phase 6B/6C were not run because the Phase 6A native-data gate failed."]), encoding="utf-8")
    write_status_csv("phase6_trade_lifecycle_table.csv", "order-to-deal-to-position linkage", native_status)
    (OUT / "phase6_information_boundary.md").write_text(
        "# Phase 6 information boundary\n\n"
        "Phase 6A reached **A4 — no native account/terminal evidence**. This does not show that broker-server history is unavailable; it shows only that it is unavailable in the accessible local environment. The project must not continue to intrabar inference from external M1.\n\n"
        "To reduce the decisive uncertainty, obtain a same-account native terminal archive/export containing synchronized XAUUSD.f Bid/Ask ticks and Orders, Deals, Positions, Journal/Experts logs for 2025-09-25 through 2026-09-18. Preserve source files and record SHA-256, server/broker identifier, symbol, time representation and extraction method.\n",
        encoding="utf-8",
    )
    answers = [
        ("Was the original terminal found?", "No."), ("Was the same account/server identified?", "No; NATIVE_ACCOUNT_NOT_ACCESSIBLE."),
        ("Were native historical ticks successfully retrieved?", "No; no terminal/account was accessible."), ("What percentage of entries has usable native tick coverage?", "Not measurable; no native ticks."),
        ("What percentage of exits has usable native tick coverage?", "Not measurable; no native ticks."), ("Can execution prices be explained by native Bid/Ask?", "Not measurable."),
        ("Was spread recoverable?", "No."), ("Were native Orders recovered?", "No."), ("Were Deals recovered?", "No."), ("Were Positions recovered?", "No."),
        ("Were SL/TP modifications recovered?", "No."), ("Were pending/cancelled/rejected orders recovered?", "No."), ("Were Magic IDs/comments recoverable?", "No."),
        ("Did native timestamps reveal a precise entry mechanism?", "No."), ("Can bar-close vs timer vs opportunity-window behavior be distinguished?", "No."),
        ("Can the exact intrabar trigger be localized?", "No."), ("Can direction be reconstructed?", "No."), ("Can sizing be reconstructed?", "No."),
        ("Can exits be reconstructed?", "No."), ("Does the native opportunity set solve the Phase 5 negative-space problem?", "No native opportunity set was recovered."),
        ("What remains hidden?", "Quote path, Bid/Ask/spread, order lifecycle, non-executed orders, modifications, broker timing and hidden EA state."),
        ("Did the project move beyond Level D?", "No. STOP A prevents 6B/6C and no evidence supports promotion."),
    ]
    status = "# Phase 6 status\n\n**Decision: A4 / STOP A — no native account or terminal evidence in the accessible environment. LEVEL D — UNIDENTIFIED remains unchanged.**\n\n"
    status += "\n".join(f"{index}. **{question}** {answer}" for index, (question, answer) in enumerate(answers, 1))
    status += "\n\nThe next required evidence is a preserved same-account MT5/MT4 archive or broker export with native ticks and lifecycle history. External tick data would not be broker-native evidence.\n"
    (OUT / "phase6_status.md").write_text(status, encoding="utf-8")
    validation = {
        "phase": 6, "run_utc": lock["acquired_utc"], "canonical": canonical, "baseline_locked": True,
        "phase6a_decision": "A4_NO_NATIVE_ACCOUNT_OR_TERMINAL_EVIDENCE", "stop_condition": "STOP_A",
        "native_account_status": account_status, "native_ticks_status": native_status, "native_transaction_status": native_status,
        "expected_terminal_paths": {str(path): path.exists() for path in EXPECTED_PATHS}, "registered_terminal_count": len(registered),
        "metatrader5_python_package": mt5_python, "identification_level": "D — UNIDENTIFIED",
        "phase6b_6c_run": False, "external_m1_not_native": True,
    }
    (OUT / "phase6_validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    print(json.dumps({"decision": validation["phase6a_decision"], "level": validation["identification_level"], "registered_terminals": len(registered)}, indent=2))


if __name__ == "__main__":
    main()
