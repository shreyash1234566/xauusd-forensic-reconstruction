import os
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def classify_file(rel_path_str: str) -> tuple[str, dict]:
    parts = rel_path_str.replace("\\", "/").split("/")
    top = parts[0]
    sub = parts[1] if len(parts) > 1 else ""
    filename = parts[-1]
    ext = Path(filename).suffix.lower()

    # Classification flags
    is_source = ext in [".py", ".mjs", ".js", ".mq5", ".toml", ".json"] and top in ["src", "scripts"]
    is_raw_data = top == "data" and ("raw" in parts or "raw_ticks" in parts or "XAUUSD" in filename or "normalized" in parts)
    is_derived_evidence = top == "outputs" or (top == "data" and "processed" in parts)
    is_doc = ext in [".md", ".txt", ".tsv"] or top == "docs"
    is_test = top == "tests" or filename.startswith("test_")

    # Phase categorization
    phase = "general"
    if top == "src":
        phase = "core_package"
    elif top == "tests":
        phase = "test_suite"
    elif top == "docs":
        phase = "documentation"
    elif top == "data":
        if "raw_ticks" in parts:
            phase = "raw_market_ticks"
        elif "normalized" in parts or "raw" in parts or "XAUUSD" in filename:
            phase = "raw_market_data"
        elif "processed" in parts:
            phase = "processed_market_data"
        else:
            phase = "raw_data"
    elif top == "outputs":
        if sub == "01a0bada-7e73-77c0-9b06-15db62fdf55d":
            phase = "phase1_base_pipeline"
        elif sub == "market_reconstruction":
            if "phase2" in filename:
                phase = "phase2_market_reconstruction"
            elif "phase3" in filename:
                phase = "phase3_intrabar_clock"
            elif "phase4" in filename:
                phase = "phase4_lifecycle_recovery"
            elif "phase5" in filename:
                phase = "phase5_observable_state"
            elif "phase6b" in filename:
                phase = "phase6b_native_artifacts"
            elif "phase6" in filename:
                phase = "phase6_native_recovery"
            elif "phase7b" in filename:
                phase = "phase7b_feed_reconciliation"
            elif "phase7c" in filename:
                phase = "phase7c_tick_validation"
            elif "phase7" in filename:
                phase = "phase7_market_identification"
            else:
                phase = "market_reconstruction_general"
        elif sub == "public_source_verification":
            phase = "phase6c_public_source_verification"
        elif sub == "strategy_reconstruction":
            if "phase8b" in filename:
                phase = "phase8b_strategy_falsification"
            elif "phase8c" in filename:
                phase = "phase8c_adversarial_reconstruction"
            elif "phase8d" in filename:
                phase = "phase8d_provenance_reconstruction"
            elif "phase8e" in filename:
                phase = "phase8e_leakage_audit_and_reconstruction"
            elif "phase10" in filename or "phase11" in filename:
                phase = "phase10_11_epoch_entry_selection"
            elif "phase12" in filename:
                phase = "phase12_exact_entry_identity_audit"
            else:
                phase = "strategy_reconstruction_general"
        elif sub == "verified_run":
            phase = "phase12_verified_run"
        else:
            phase = f"outputs_{sub}"
    elif top == "scripts":
        if "phase2" in filename:
            phase = "phase2_scripts"
        elif "phase3" in filename:
            phase = "phase3_scripts"
        elif "phase4" in filename:
            phase = "phase4_scripts"
        elif "phase5" in filename:
            phase = "phase5_scripts"
        elif "phase6b" in filename:
            phase = "phase6b_scripts"
        elif "phase6" in filename:
            phase = "phase6_scripts"
        elif "phase7b" in filename:
            phase = "phase7b_scripts"
        elif "phase7c" in filename:
            phase = "phase7c_scripts"
        elif "phase7" in filename:
            phase = "phase7_scripts"
        elif "phase8b" in filename:
            phase = "phase8b_scripts"
        elif "phase8c" in filename:
            phase = "phase8c_scripts"
        elif "phase8d" in filename:
            phase = "phase8d_scripts"
        elif "phase8e" in filename:
            phase = "phase8e_scripts"
        elif "phase10" in filename or "phase11" in filename or "tickfeat10" in filename or "clockfix10" in filename:
            phase = "phase10_11_scripts"
        elif "phase12" in filename:
            phase = "phase12_scripts"
        elif "public_source" in filename:
            phase = "phase6c_scripts"
        else:
            phase = "pipeline_scripts"

    flags = {
        "is_source_code": is_source,
        "is_raw_data": is_raw_data,
        "is_derived_evidence": is_derived_evidence,
        "is_documentation": is_doc,
        "is_test": is_test,
    }
    return phase, flags

def generate_manifest():
    manifest_entries = []
    total_bytes = 0

    # Read git status / tracked candidates respecting .gitignore
    import subprocess
    cmd = ["git", "status", "--porcelain", "-uall"]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)

    # Alternatively get list from git status
    tracked_files = []
    for line in proc.stdout.splitlines():
        if line.startswith("?? ") or line.startswith(" M ") or line.startswith("A "):
            rel_path = line[3:].strip().strip('"')
            tracked_files.append(rel_path)

    # If git status gave directories, expand them
    all_files = []
    for tf in tracked_files:
        p = ROOT / tf
        if p.is_file():
            all_files.append(p)
        elif p.is_dir():
            for sub_p in p.rglob("*"):
                if sub_p.is_file():
                    all_files.append(sub_p)

    # Sort deterministically
    all_files = sorted(set(all_files), key=lambda x: str(x.relative_to(ROOT)).replace("\\", "/"))

    print(f"Total candidate files to index: {len(all_files)}")

    for p in all_files:
        rel = p.relative_to(ROOT)
        rel_posix = str(rel).replace("\\", "/")
        if rel_posix in ["repository_manifest.json", "scripts/generate_manifest.py"]:
            continue
        sz = p.stat().st_size
        total_bytes += sz
        h = compute_sha256(p)
        phase, flags = classify_file(rel_posix)
        flags["is_large_file"] = sz > 10 * 1024 * 1024

        manifest_entries.append({
            "path": rel_posix,
            "size_bytes": sz,
            "sha256": h,
            "phase": phase,
            "flags": flags
        })

    manifest = {
        "project_name": "xauusd-forensic-reconstruction",
        "description": "Forensic reverse-engineering and econometric identifiability audit of institutional XAUUSD trading strategy",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_files": len(manifest_entries),
        "total_bytes": total_bytes,
        "total_megabytes": round(total_bytes / (1024 * 1024), 2),
        "canonical_trade_count": 423,
        "canonical_epoch_count": 420,
        "authoritative_phases": [
            "Phase 1: Baseline Behavioral Fingerprint & Evidence Hierarchy",
            "Phase 2: Event Panel & Trade Opportunity Universe",
            "Phase 3: Intrabar State Machine & Clock Trigger Analysis",
            "Phase 4: Order/Deal Lifecycle & Microstructure Recovery",
            "Phase 5: Observable State Space, Feature Ablation & Information Boundary",
            "Phase 6: Native Environment Inventory & Journal Reconstruction",
            "Phase 6b: Native Artifact Ingestion & Forensic Schema Validation",
            "Phase 6c: Multidimensional Public Source & IP Verification",
            "Phase 7: Market Feed Identification & Structural Comparison",
            "Phase 7b: Millisecond Market-Feed Reconciliation & L2 Depth Modeling",
            "Phase 7c: Real Raw-Tick Validation & Canonical Ledger Lock (423 trades, 7.1M+ ticks)",
            "Phase 8b: Strategy Falsification, Counterfactual Controls & Sizing/Exit Decomposition",
            "Phase 8c: Adversarial Reconstruction, Counterfactual Replay & Identifiability Boundary",
            "Phase 8d: Provenance Reconstruction, Latent State & Point-Process Intensity",
            "Phase 8e: Leakage Audit, Flat-State Signal Recovery, Orthogonal Two-Model Reconstruction & MQL5 EA"
        ],
        "experimental_research_phases": [
            "Phase 10/11: Epoch-Level Entry Selection, M3/M4 Linear Predictors & Discovery-Frozen Lockbox Evaluation",
            "Phase 12: Complete-Ledger Deterministic Entry-Rule Identity Audit (U = E ∪ F, N_U = 206,066)"
        ],
        "files": manifest_entries
    }

    manifest_path = ROOT / "repository_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Manifest written successfully to: {manifest_path}")
    print(f"Indexed {len(manifest_entries)} files ({total_bytes / (1024 * 1024):.2f} MB).")

if __name__ == "__main__":
    generate_manifest()
