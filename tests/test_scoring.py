"""Tests for compliance status derivation and the headline roll-ups."""

from datetime import date

import pytest

from omnis.models import EvidenceRecord, Requirement
from omnis.scoring import automation_rate, omniscience_index, score_requirement
from omnis.scoring.scorer import score_corpus

REQ = Requirement(
    id="POL-X-R1", policy_id="POL-X", policy_title="X", number=1, text="x",
    audit_frequency="Monthly",  # 30-day window
)


def ev(evidence_id="E", status="Approved", freshness_days=5, confidence=0.9, evidence_type="Audit_Log"):
    return EvidenceRecord(
        evidence_id=evidence_id,
        requirement_id="POL-X-R1",
        requirement_description="d",
        framework="GDPR",
        evidence_type=evidence_type,
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 4, 1),
        freshness_days=freshness_days,
        evidence_summary="s",
        status=status,
        confidence_score=confidence,
    )


def test_status_compliant():
    s = score_requirement(REQ, [ev(status="Approved", freshness_days=5, confidence=0.9)])
    assert s.status == "COMPLIANT"
    assert s.confidence > 0.0
    assert s.evidence_ids == ["E"]


def test_status_gap_on_rejected():
    s = score_requirement(REQ, [ev(evidence_id="R", status="Rejected")])
    assert s.status == "GAP"


def test_status_gap_on_stale_without_approval():
    # Monthly window 30; age 60 and not Approved -> failing.
    s = score_requirement(REQ, [ev(evidence_id="S", status="Needs_Update", freshness_days=60)])
    assert s.status == "GAP"


def test_status_gap_on_contradiction():
    # Approved but low confidence -> contradicted -> failing.
    s = score_requirement(REQ, [ev(evidence_id="C", status="Approved", confidence=0.5)])
    assert s.status == "GAP"


def test_status_partial_mixed():
    good = ev(evidence_id="G", status="Approved", freshness_days=5, confidence=0.9)
    bad = ev(evidence_id="B", status="Rejected")
    s = score_requirement(REQ, [good, bad])
    assert s.status == "PARTIAL"
    assert set(s.evidence_ids) == {"G", "B"}


def test_status_unknown_when_no_evidence():
    s = score_requirement(REQ, [])
    assert s.status == "UNKNOWN"
    assert s.confidence == 0.0
    assert "missing evidence" in s.rationale.lower()


def test_compliant_requires_no_failing():
    # One good and one stale-unapproved -> not COMPLIANT, it is PARTIAL.
    good = ev(evidence_id="G", status="Approved", freshness_days=5, confidence=0.9)
    stale = ev(evidence_id="S", status="Needs_Update", freshness_days=90)
    assert score_requirement(REQ, [good, stale]).status == "PARTIAL"


def test_omniscience_index_hand_fixture():
    r1 = Requirement(id="A", policy_id="P", policy_title="P", number=1, text="t", audit_frequency="Monthly")
    r2 = Requirement(id="B", policy_id="P", policy_title="P", number=2, text="t", audit_frequency="Monthly")
    # r1 covered by fresh (age 0 -> freshness 1.0), confident (1.0) evidence; r2 uncovered.
    fresh_conf = ev(evidence_id="E1", freshness_days=0, confidence=1.0)
    mapped = {"A": [fresh_conf], "B": []}
    # quality_A = 0.4*1 + 0.3*1.0 + 0.3*1.0 = 1.0 ; quality_B = 0 ; index = 100*(1.0)/2
    assert omniscience_index([r1, r2], mapped) == pytest.approx(50.0)

    # Now age 30 (Monthly half-life) -> freshness 0.5, confidence 0.8.
    decayed = ev(evidence_id="E2", freshness_days=30, confidence=0.8)
    mapped2 = {"A": [decayed], "B": []}
    # quality_A = 0.4 + 0.3*0.5 + 0.3*0.8 = 0.79 ; index = 100*0.79/2 = 39.5
    assert omniscience_index([r1, r2], mapped2) == pytest.approx(39.5)


def test_automation_rate_math():
    records = [
        ev(evidence_id="1", evidence_type="Audit_Log"),  # auto
        ev(evidence_id="2", evidence_type="Configuration_Snapshot"),  # auto
        ev(evidence_id="3", evidence_type="Screenshot"),  # manual
        ev(evidence_id="4", evidence_type="Training_Record"),  # manual
    ]
    assert automation_rate(records) == pytest.approx(50.0)
    assert automation_rate([]) == 0.0


def test_score_corpus_rolls_up_methods_and_statuses():
    from omnis.mapping import map_evidence

    reqs = [REQ]
    records = [ev(evidence_id="E1", status="Approved", freshness_days=5, confidence=0.9)]
    links = map_evidence(records, reqs)  # exact id match on POL-X-R1
    scores, summary = score_corpus(reqs, records, links)
    assert summary.total_requirements == 1
    assert summary.total_evidence == 1
    assert summary.method_breakdown.get("exact_id") == 1
    assert summary.status_breakdown.get("COMPLIANT") == 1
    assert 0.0 <= summary.omniscience_index <= 100.0
