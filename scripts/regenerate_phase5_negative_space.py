"""Regenerate the hierarchy of matched non-trade controls from the saved feature table."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from phase5_observable_reconstruction import negative_space
from reverse_trade.pipeline import load_trades


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "market_reconstruction"


def main() -> None:
    panel = pd.read_csv(OUT / "phase5_feature_table.csv.gz", parse_dates=["timestamp"])
    trades, _ = load_trades(ROOT / "data" / "raw" / "trades_raw.tsv")
    negative = negative_space(panel, trades)
    negative.to_csv(OUT / "phase5_negative_space_table.csv.gz", index=False, compression="gzip")
    summary = negative.groupby(["control_set", "fallback"], as_index=False).size().rename(columns={"size": "rows"})
    lines = ["| " + " | ".join(summary.columns) + " |", "| " + " | ".join("---" for _ in summary.columns) + " |"]
    lines += ["| " + " | ".join(str(value) for value in row) + " |" for row in summary.itertuples(index=False, name=None)]
    (OUT / "phase5_negative_space_analysis.md").write_text(
        "# Phase 5 negative-space analysis\n\n"
        f"The hierarchy creates {len(negative)} ticket-control rows from {negative.ticket.nunique()} ledger tickets. Levels A–E progressively match clock phase, session, volatility, location and momentum. Level F selects the nearest temporal neighbor satisfying the level-E constraints. Explicit fallbacks are retained. These are external-M1-proxy similarities, not proof of equal broker quotes or hidden EA state.\n\n"
        + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print({"negative_rows": len(negative), "tickets": negative.ticket.nunique()})


if __name__ == "__main__":
    main()
