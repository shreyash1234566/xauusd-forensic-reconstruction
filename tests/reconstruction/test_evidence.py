from pathlib import Path

from reverse_trade.reconstruction.evidence import (
    CANONICAL_EPOCH_COUNT,
    CANONICAL_RECORD_COUNT,
    audit_canonical_evidence,
    build_decision_epochs,
    load_canonical_records,
)


ROOT = Path(__file__).resolve().parents[2]


def test_canonical_evidence_and_epochs_are_preserved() -> None:
    audit = audit_canonical_evidence(ROOT)
    records = load_canonical_records(ROOT)
    annotated, epochs = build_decision_epochs(records)
    assert audit["ledger"]["rows"] == CANONICAL_RECORD_COUNT
    assert len(annotated) == CANONICAL_RECORD_COUNT
    assert len(epochs) == CANONICAL_EPOCH_COUNT
    assert int(epochs["record_count"].eq(2).sum()) == 3
    assert set(annotated.loc[annotated["is_epoch_anchor"], "epoch_id"]) == set(range(CANONICAL_EPOCH_COUNT))
    assert set(annotated["recorded_price_semantics"]) == {"recorded_entry_price_supported_by_phase7c"}
