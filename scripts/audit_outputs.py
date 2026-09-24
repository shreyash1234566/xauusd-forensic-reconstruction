import json
import pandas as pd
from pathlib import Path

prev_dir = Path("outputs/01a0bada-7e73-77c0-9b06-15db62fdf55d")
new_dir = Path("outputs/verified_run")

print("--- AUDITING analysis_metrics.json in 01a0bada... ---")
with open(prev_dir / "analysis_metrics.json", "r", encoding="utf-8") as f:
    m_prev = json.load(f)

print("Summary in prev metrics:")
print("  Observations:", m_prev.get("summary", {}).get("observations"))
print("  Start open:", m_prev.get("summary", {}).get("start_open"))
print("  End open:", m_prev.get("summary", {}).get("end_open"))
print("  Buy count:", m_prev.get("summary", {}).get("buy_count"))
print("  Sell count:", m_prev.get("summary", {}).get("sell_count"))
print("  Total PnL:", m_prev.get("summary", {}).get("total_pnl"))
print("  Symbol in data_quality:", m_prev.get("data_quality", {}).get("symbol_values"))
print("  Distinct open dates:", m_prev.get("summary", {}).get("distinct_open_dates"))

with open(new_dir / "analysis_metrics.json", "r", encoding="utf-8") as f:
    m_new = json.load(f)

print("\nSummary in newly generated verified_run metrics:")
print("  Observations:", m_new.get("summary", {}).get("observations"))
print("  Start open:", m_new.get("summary", {}).get("start_open"))
print("  End open:", m_new.get("summary", {}).get("end_open"))
print("  Buy count:", m_new.get("summary", {}).get("buy_count"))
print("  Sell count:", m_new.get("summary", {}).get("sell_count"))
print("  Total PnL:", m_new.get("summary", {}).get("total_pnl"))
print("  Symbol in data_quality:", m_new.get("data_quality", {}).get("symbol_values"))
print("  Distinct open dates:", m_new.get("summary", {}).get("distinct_open_dates"))

# Compare key files
print("\n--- COMPARING TABLES ---")
table_files = [
    "statistical_tests.csv",
    "change_point_tests.csv",
    "gmm_model_comparison.csv",
    "hmm_model_comparison.csv",
    "confidence_table.csv",
    "specification_coverage.csv",
    "position_size_summary.csv",
    "direction_transition_matrix.csv",
    "holding_time_phases.csv"
]

for tf in table_files:
    p1 = prev_dir / "tables" / tf
    p2 = new_dir / "tables" / tf
    if p1.exists() and p2.exists():
        df1 = pd.read_csv(p1)
        df2 = pd.read_csv(p2)
        match = df1.equals(df2)
        print(f"Table {tf}: identical = {match}, rows = {len(df1)}")
    else:
        print(f"Table {tf}: exists in prev={p1.exists()}, new={p2.exists()}")
