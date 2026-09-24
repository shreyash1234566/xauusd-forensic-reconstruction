"""
Phase 8B: Master Pipeline Runner
Allows executing individual stages, cheap forensic stages only, or the entire pipeline.
"""

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

STAGES = [
    ("01", "phase8b_01_verify_inputs.py", "Verify Inputs & Hashes", "cheap"),
    ("02", "phase8b_02_entry_features.py", "Extract Pre-Entry Features", "cheap"),
    ("03", "phase8b_03_tick_microstructure.py", "Extract Tick Microstructure", "medium"),
    ("04", "phase8b_04_counterfactuals.py", "Counterfactuals & Falsification", "cheap"),
    ("05", "phase8b_05_exit_models.py", "Exit Model Trajectory Simulations", "medium"),
    ("06", "phase8b_06_sizing_state.py", "Position Sizing State Machine", "cheap"),
    ("07", "phase8b_07_direction.py", "Directional Predictability Audit", "ml"),
    ("08", "phase8b_08_walkforward.py", "Walk-Forward Expanding Validation", "ml"),
]

def run_stage(stage_script):
    p = SCRIPTS_DIR / stage_script
    print(f"\n>>> Running: {p.name}...")
    res = subprocess.run([sys.executable, str(p)], capture_output=False)
    if res.returncode != 0:
        print(f"[FAIL] Stage {stage_script} failed with exit code {res.returncode}")
        return False
    return True

def main():
    args = sys.argv[1:]
    if "--cheap-only" in args:
        selected = [s for s in STAGES if s[3] in ["cheap", "medium"] and s[0] in ["01", "02", "03", "04"]]
    elif "--forensic-deterministic" in args:
        selected = [s for s in STAGES if s[0] in ["01", "02", "03", "04", "05", "06"]]
    elif "--stage" in args:
        stage_nums = args[args.index("--stage") + 1:]
        selected = [s for s in STAGES if s[0] in stage_nums]
    else:
        selected = STAGES

    print(f"Executing {len(selected)} stages...")
    for s_num, s_script, s_desc, s_type in selected:
        success = run_stage(s_script)
        if not success:
            sys.exit(1)

    print("\n>>> All requested stages executed successfully!")

if __name__ == "__main__":
    main()
