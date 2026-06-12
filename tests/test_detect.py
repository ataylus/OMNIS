"""Tests for the rule-based detector: each rule, priority order, and exceptions."""

from datetime import date

from omnis.detect import RuleBasedDetector
from omnis.models import EvidenceRecord

KNOWN = {"SYN-REQ-001", "SYN-REQ-002"}


def rec(**overrides):
    base = dict(
        evidence_id="E0",
        requirement_id="SYN-REQ-001",
        requirement_description="d",
        framework="GDPR",
        evidence_type="config",
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 4, 1),
        freshness_days=10,
        evidence_summary="s",
        status="Approved",
        confidence_score=0.9,
    )
    base.update(overrides)
    return EvidenceRecord(**base)


def detect(record, known=KNOWN):
    return RuleBasedDetector(known).predict(record)


def test_stale_evidence_rule():
    p = detect(rec(freshness_days=120, status="Needs_Update"))
    assert p is not None and p.anomaly_class == "STALE_EVIDENCE"
    assert "120 days old" in p.reason
    assert 0.0 < p.confidence <= 0.99


def test_stale_exempts_approved_evidence():
    # Old but Approved -> NOT stale (the exception the synthetic bench exercises).
    assert detect(rec(freshness_days=200, status="Approved")) is None


def test_stale_boundary_strict():
    # Window is 90: exactly 90 is fresh, 91 is stale.
    assert detect(rec(freshness_days=90, status="Needs_Update")) is None
    p = detect(rec(freshness_days=91, status="Needs_Update"))
    assert p is not None and p.anomaly_class == "STALE_EVIDENCE"


def test_compliance_gap_rule():
    p = detect(rec(status="Rejected", freshness_days=10))
    assert p is not None and p.anomaly_class == "COMPLIANCE_GAP"
    assert "Rejected" in p.reason


def test_unreviewed_rule():
    p = detect(rec(status="Pending_Review", freshness_days=10))
    assert p is not None and p.anomaly_class == "UNREVIEWED_EVIDENCE"


def test_missing_documentation_rule():
    p = detect(rec(status="Needs_Update", confidence_score=0.5, freshness_days=10))
    assert p is not None and p.anomaly_class == "MISSING_DOCUMENTATION"
    assert "0.5" in p.reason


def test_missing_documentation_boundary_strict():
    # < 0.6 fires; exactly 0.6 does not.
    assert detect(rec(status="Approved", confidence_score=0.6, freshness_days=10)) is None
    p = detect(rec(status="Approved", confidence_score=0.59, freshness_days=10))
    assert p is not None and p.anomaly_class == "MISSING_DOCUMENTATION"


def test_incomplete_mapping_rule():
    p = detect(rec(requirement_id="ORPHAN-REQ-1234", status="Approved", freshness_days=10))
    assert p is not None and p.anomaly_class == "INCOMPLETE_MAPPING"
    assert "ORPHAN-REQ-1234" in p.reason


def test_incomplete_mapping_inert_without_known_ids():
    # With no known requirement set, the mapping rule cannot judge and stays silent.
    detector = RuleBasedDetector(known_requirement_ids=None)
    assert detector.predict(rec(requirement_id="ORPHAN-REQ-1", freshness_days=10)) is None


def test_priority_stale_beats_rejected():
    # Old AND rejected -> STALE wins (age is the higher-priority signal).
    p = detect(rec(status="Rejected", freshness_days=150))
    assert p is not None and p.anomaly_class == "STALE_EVIDENCE"


def test_clean_record_returns_none():
    assert detect(rec(status="Approved", confidence_score=0.95, freshness_days=10)) is None


def test_every_prediction_is_explainable():
    p = detect(rec(status="Rejected", freshness_days=10))
    assert p.reason and isinstance(p.reason, str)
    assert 0.0 <= p.confidence <= 1.0
