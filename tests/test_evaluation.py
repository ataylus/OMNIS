"""Tests for the evaluation harness, with hand-computed expected metrics."""

from datetime import date

import pytest

from omnis.evaluation import BaselineDetector, evaluate, load_label_overrides
from omnis.models import EvidenceRecord


def make_record(evidence_id, freshness_days, anomaly_marker):
    return EvidenceRecord(
        evidence_id=evidence_id,
        requirement_id="REQ1",
        requirement_description="d",
        framework="GDPR",
        evidence_type="config",
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 4, 1),
        freshness_days=freshness_days,
        evidence_summary="s",
        status="Approved",
        anomaly_marker=anomaly_marker,
    )


# Hand-built corpus. BaselineDetector predicts STALE_EVIDENCE when freshness>90.
#   E0 STALE/100 -> pred STALE  : TP  (class match)
#   E1 STALE/50  -> pred None   : FN
#   E2 blank/120 -> pred STALE  : FP
#   E3 blank/30  -> pred None   : TN
#   E4 GAP/200   -> pred STALE  : TP  (binary), class mismatch
#   E5 blank/95  -> pred STALE  : FP
FIXTURE = [
    make_record("E0", 100, "STALE_EVIDENCE"),
    make_record("E1", 50, "STALE_EVIDENCE"),
    make_record("E2", 120, None),
    make_record("E3", 30, None),
    make_record("E4", 200, "COMPLIANCE_GAP"),
    make_record("E5", 95, None),
]


@pytest.fixture(scope="module")
def result():
    return evaluate(FIXTURE, BaselineDetector())


def test_binary_confusion_counts(result):
    assert (result.tp, result.fp, result.fn, result.tn) == (2, 2, 1, 1)
    assert result.total == 6


def test_binary_precision_recall_f1(result):
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(2 / 3)
    assert result.f1 == pytest.approx(2 * 0.5 * (2 / 3) / (0.5 + 2 / 3))


def test_per_class_stale_evidence(result):
    stale = result.per_class["STALE_EVIDENCE"]
    assert stale["precision"] == pytest.approx(0.25)  # 1 correct of 4 predicted
    assert stale["recall"] == pytest.approx(0.5)  # 1 of 2 true
    assert stale["f1"] == pytest.approx(2 * 0.25 * 0.5 / (0.25 + 0.5))
    assert stale["support"] == 2
    assert stale["predicted"] == 4


def test_per_class_compliance_gap(result):
    gap = result.per_class["COMPLIANCE_GAP"]
    assert gap["precision"] == 0.0
    assert gap["recall"] == 0.0
    assert gap["support"] == 1
    assert gap["predicted"] == 0


def test_confusion_matrix(result):
    assert result.confusion["STALE_EVIDENCE"] == {"STALE_EVIDENCE": 1, "NONE": 1}
    assert result.confusion["COMPLIANCE_GAP"] == {"STALE_EVIDENCE": 1}
    assert result.confusion["NONE"] == {"STALE_EVIDENCE": 2, "NONE": 1}


def test_labels_override_changes_truth(tmp_path):
    records = [
        make_record("E0", 100, None),  # in-band: negative; override: positive
        make_record("E1", 10, None),  # in-band: negative; override: negative
    ]
    # Without overrides: E0 fires (pred STALE) but truth negative -> FP only.
    base = evaluate(records, BaselineDetector())
    assert (base.tp, base.fp, base.fn, base.tn) == (0, 1, 0, 1)

    labels = tmp_path / "labels.csv"
    labels.write_text(
        "evidence_id,is_anomaly,anomaly_type\n"
        "E0,1,STALE_EVIDENCE\n"
        "E1,0,\n",
        encoding="utf-8",
    )
    overrides = load_label_overrides(labels)
    overridden = evaluate(records, BaselineDetector(), overrides, str(labels))
    # Now E0 truth is positive and the detector fires on it -> a true positive.
    assert (overridden.tp, overridden.fp, overridden.fn, overridden.tn) == (1, 0, 0, 1)
    assert overridden.precision == pytest.approx(1.0)
    assert overridden.recall == pytest.approx(1.0)
    assert overridden.label_source == str(labels)
