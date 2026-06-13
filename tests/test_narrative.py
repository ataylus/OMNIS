"""Tests for the audit narrative template, including the four judged edge cases."""

from datetime import date

from omnis.models import EvidenceRecord, Requirement
from omnis.narrative import generate_narrative
from omnis.scoring import score_requirement

REQ = Requirement(
    id="POL-AUD-001-R1", policy_id="POL-AUD-001", policy_title="Audit Logging",
    number=1, text="All access to sensitive data must be logged",
    evidence_source="Application Logs, Database Audit Trails", audit_frequency="Monthly",
)


def ev(evidence_id="E", status="Approved", freshness_days=5, confidence=0.9):
    return EvidenceRecord(
        evidence_id=evidence_id,
        requirement_id="POL-AUD-001-R1",
        requirement_description="d",
        framework="GDPR",
        evidence_type="Audit_Log",
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 4, 1),
        freshness_days=freshness_days,
        evidence_summary="s",
        status=status,
        confidence_score=confidence,
    )


def narrate(records):
    score = score_requirement(REQ, records)
    return score.status, generate_narrative(REQ, score, records)


def _no_em_dash(text: str) -> bool:
    return "—" not in text and "–" not in text


def test_unknown_missing_evidence_narrative():
    status, text = narrate([])
    assert status == "UNKNOWN"
    assert "No evidence" in text and "coverage gap" in text
    assert REQ.text in text
    assert _no_em_dash(text)


def test_compliant_narrative():
    status, text = narrate([ev(status="Approved", freshness_days=5, confidence=0.95)])
    assert status == "COMPLIANT"
    assert "control is supported" in text
    assert _no_em_dash(text)


def test_conflicting_evidence_narrative():
    good = ev(evidence_id="G", status="Approved", freshness_days=5, confidence=0.9)
    bad = ev(evidence_id="B", status="Rejected")
    status, text = narrate([good, bad])
    assert status == "PARTIAL"
    assert "conflict" in text.lower()
    assert _no_em_dash(text)


def test_ambiguous_evidence_narrative():
    status, text = narrate([ev(evidence_id="P", status="Pending_Review", confidence=0.8)])
    assert status == "PARTIAL"
    assert "inconclusive" in text.lower()
    assert _no_em_dash(text)


def test_low_confidence_narrative():
    # Approved but below the confidence threshold -> contradicted -> GAP, and the
    # narrative must call out low confidence specifically.
    status, text = narrate([ev(evidence_id="L", status="Approved", confidence=0.5)])
    assert status == "GAP"
    assert "low confidence" in text.lower() and "confidence below" in text.lower()
    assert _no_em_dash(text)


def test_narrative_distinct_per_edge_case():
    unknown = narrate([])[1]
    conflicting = narrate([ev("G", "Approved", 5, 0.9), ev("B", "Rejected")])[1]
    ambiguous = narrate([ev("P", "Pending_Review", 5, 0.8)])[1]
    low_conf = narrate([ev("L", "Approved", 5, 0.5)])[1]
    assert len({unknown, conflicting, ambiguous, low_conf}) == 4


def test_recommendation_present():
    _status, text = narrate([])
    assert "Recommended next step:" in text
