"""
Phase 8D Master Orchestrator: End-to-End Hidden Trigger, Latent State, and Execution-Provenance Pipeline.
Runs all 5 stages in sequence and verifies integrity of all 10 forensic artifacts.
"""

from pathlib import Path
import time
import subprocess
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
OUTPUTS_DIR = ROOT / "outputs" / "strategy_reconstruction"

REQUIRED_ARTIFACTS = [
    ("phase8d_tick_event_features.csv", 846, 100),
    ("phase8d_entry_event_catalog.csv", 846, 8),
    ("phase8d_event_alignment.csv", 60, 4),
    ("phase8d_matched_state_controls.csv", 420, 8),
    ("phase8d_latent_state.csv", 423, 10),
    ("phase8d_trade_intensity.csv", 4, 3),
    ("phase8d_information_boundary.csv", 4, 4),
    ("phase8d_entry_replay.csv", 1, 8),
    ("phase8d_oos_results.csv", 3, 6)
]

def run_stage(script_name):
    script_path = SCRIPTS_DIR / script_name
    print(f"\n>>> EXECUTING: {script_name}...")
    t0 = time.time()
    res = subprocess.run(["python", str(script_path)], capture_output=True, text=True)
    dt = time.time() - t0
    if res.returncode != 0:
        print(f"[FAIL] {script_name} failed with exit code {res.returncode}")
        print(res.stderr)
        raise RuntimeError(f"Stage {script_name} failed.")
    print(res.stdout.strip())
    print(f"[SUCCESS] {script_name} finished in {dt:.2f}s")

def verify_artifacts():
    print("\n=================================================================")
    print("PHASE 8D FORENSIC ARTIFACT VERIFICATION AUDIT")
    print("=================================================================")
    all_passed = True
    for fname, min_rows, min_cols in REQUIRED_ARTIFACTS:
        p = OUTPUTS_DIR / fname
        if not p.exists():
            print(f"[FAIL] Missing artifact: {fname}")
            all_passed = False
            continue
        try:
            df = pd.read_csv(p)
            n_rows, n_cols = len(df), len(df.columns)
            if n_rows < min_rows or n_cols < min_cols:
                print(f"[WARN] {fname} shape ({n_rows}, {n_cols}) < expected min ({min_rows}, {min_cols})")
                all_passed = False
            else:
                print(f"[PASS] {fname:<36} | {n_rows:>5} rows | {n_cols:>3} cols | {p.stat().st_size / 1024:>7.1f} KB")
        except Exception as e:
            print(f"[FAIL] Error reading {fname}: {e}")
            all_passed = False

    return all_passed

def main():
    print("=================================================================")
    print("PHASE 8D - MASTER PIPELINE EXECUTION")
    print("=================================================================")
    t0 = time.time()

    stages = [
        "phase8d_01_microstructure_windows.py",
        "phase8d_02_event_sequences_and_alignment.py",
        "phase8d_03_matched_controls_and_direction.py",
        "phase8d_04_latent_state_and_intensity.py",
        "phase8d_05_information_boundary_and_replay.py"
    ]

    for s in stages:
        run_stage(s)

    ok = verify_artifacts()
    elapsed = time.time() - t0
    print(f"\n=================================================================")
    print(f"PHASE 8D PIPELINE COMPLETED IN {elapsed:.2f}s | STATUS: {'ALL ARTIFACTS VERIFIED' if ok else 'FAILED'}")
    print("=================================================================\n")

if __name__ == "__main__":
    main()
