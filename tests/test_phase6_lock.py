from pathlib import Path

from scripts.phase6_native_recovery import sha256


def test_phase6_hash_is_stable_for_identical_content(tmp_path: Path) -> None:
    target = tmp_path / "ledger.tsv"
    target.write_text("unchanged\n", encoding="utf-8")
    assert sha256(target) == sha256(target)
