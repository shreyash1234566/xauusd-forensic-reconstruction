"""
Master Pipeline Orchestrator for Phase 8C: Adversarial Reconstruction of the Proposed Strategy
Runs Stages 1 through 6 sequentially and verifies all output CSVs and datasets.
"""

from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
OUTPUT_DIR = ROOT / "outputs" / "strategy_reconstruction"

STAGES = [
    ("Stage 1: Standalone Causal Replayer Simulation", "phase8c_candidate_replayer.py"),
    ("Stage 2: Counterfactual Explosion & Selectivity Ablation", "phase8c_counterfactual_explosion.py"),
    ("Stage 3: Parameter Sensitivity, Clock Models & Directional Benchmark", "phase8c_parameter_identifiability.py"),
    ("Stage 4: Exit Falsification, Critical Exit Test & Hazard Analysis", "phase8c_exit_falsification.py"),
    ("Stage 5: Sizing State Machine, Overlap Audit & MDL Penalty", "phase8c_state_machine_audit.py"),
    ("Stage 6: Trade-by-Trade Comparison & Chronological OOS Validation", "phase8c_oos_validation_and_matching.py")
]

REQUIRED_OUTPUTS = [
    "phase8c_generated_trades.csv",
    "phase8c_candidate_signals.csv",
    "phase8c_counterfactual_explosion.csv",
    "phase8c_session_boundary_audit.csv",
    "phase8c_atr_sensitivity.csv",
    "phase8c_impulse_sensitivity.csv",
    "phase8c_directional_rules.csv",
    "phase8c_entry_architecture_comparison.csv",
    "phase8c_critical_exit_test.csv",
    "phase8c_exit_model_falsification.csv",
    "phase8c_exit_parameter_grid.csv",
    "phase8c_holding_time_hazard.csv",
    "phase8c_sizing_state_benchmark.csv",
    "phase8c_overlap_audit.csv",
    "phase8c_complexity_mdl_audit.csv",
    "phase8c_match_tolerance_bands.csv",
    "phase8c_trade_by_trade_comparison.csv",
    "phase8c_oos_validation_results.csv"
]

def main():
    print("==========================================================================")
    print("STARTING PHASE 8C ADVERSARIAL RECONSTRUCTION MASTER PIPELINE")
    print("==========================================================================")
    t0 = time.time()

    for title, script_name in STAGES:
        script_path = SCRIPTS_DIR / script_name
        print(f"\n>>> Running {title} ({script_name})...")
        res = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[FAIL] Error running {script_name}:")
            print(res.stderr)
            sys.exit(1)
        else:
            print(res.stdout.strip())

    print("\n==========================================================================")
    print("VERIFYING GENERATED OUTPUT ARTIFACTS")
    print("==========================================================================")
    missing = []
    for out_name in REQUIRED_OUTPUTS:
        p = OUTPUT_DIR / out_name
        if p.exists() and p.stat().st_size > 0:
            print(f"  [OK] {out_name} ({p.stat().st_size:,} bytes)")
        else:
            print(f"  [MISSING] {out_name}")
            missing.append(out_name)

    if missing:
        print(f"\n[FAIL] Missing {len(missing)} required output files.")
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"\n[SUCCESS] Phase 8C Master Pipeline executed successfully in {elapsed:.2f} seconds.")
    print("==========================================================================")

if __name__ == "__main__":
    main()
