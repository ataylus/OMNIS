"""Tests for the integrity checks, each driven by a tiny synthetic fixture."""

from datetime import date

from omnis.integrity import checks
from omnis.models import EvidenceRecord, Requirement


def make_record(evidence_id="EVD0", **overrides):
    """Build an EvidenceRecord with sensible, defect-free defaults."""
    base = dict(
        evidence_id=evidence_id,
        requirement_id="POL-ENC-001-R1",
        requirement_description="unique description " + evidence_id,
        framework="GDPR",
        evidence_type="config",
        collected_by="Tester",
        collector_email="t@company.com",
        collection_date=date(2026, 4, 1),
        freshness_days=14,
        evidence_summary="summary",
        reviewed_by="Reviewer",
        reviewer_email="r@company.com",
        review_date=date(2026, 4, 10),
        evidence_location="Vault-1/Path-1",
        confidence_score=0.9,
        status="Approved",
        anomaly_marker=None,
    )
    base.update(overrides)
    return EvidenceRecord(**base)


REQS = [Requirement(id="POL-ENC-001-R1", policy_id="POL-ENC-001", policy_title="Enc", number=1, text="x")]


def test_duplicate_description_fires_when_dominant():
    records = [make_record(f"E{i}", requirement_description="same") for i in range(6)]
    records.append(make_record("E6", requirement_description="different"))
    finding = checks.duplicate_description(records)
    assert finding is not None
    assert finding.severity == "HIGH"
    assert finding.affected_count == 6


def test_duplicate_description_silent_when_varied():
    records = [make_record(f"E{i}", requirement_description=f"desc-{i}") for i in range(6)]
    assert checks.duplicate_description(records) is None


def test_orphan_requirement_refs_counts_and_samples():
    records = [
        make_record("E0", requirement_id="POL-ENC-001-R1"),  # known
        make_record("E1", requirement_id="REQ999"),  # orphan
        make_record("E2", requirement_id="REQ888"),  # orphan
    ]
    finding = checks.orphan_requirement_refs(records, REQS)
    assert finding is not None
    assert finding.affected_count == 2
    assert set(finding.affected_ids) == {"REQ999", "REQ888"}


def test_orphan_requirement_refs_silent_when_all_known():
    records = [make_record("E0", requirement_id="POL-ENC-001-R1")]
    assert checks.orphan_requirement_refs(records, REQS) is None


def test_impossible_review_dates_fires_only_on_reversed():
    good = make_record("E0", collection_date=date(2026, 4, 1), review_date=date(2026, 4, 10))
    bad = make_record("E1", collection_date=date(2026, 4, 10), review_date=date(2026, 4, 1))
    finding = checks.impossible_review_dates([good, bad])
    assert finding is not None
    assert finding.affected_ids == ["E1"]


def test_status_confidence_contradiction():
    approved_low = make_record("E0", status="Approved", confidence_score=0.5)
    approved_high = make_record("E1", status="Approved", confidence_score=0.9)
    rejected_low = make_record("E2", status="Rejected", confidence_score=0.3)
    finding = checks.status_confidence_contradiction([approved_low, approved_high, rejected_low])
    assert finding is not None
    assert finding.affected_ids == ["E0"]


def test_freshness_field_consistency_uses_reference_date():
    ref = checks.REFERENCE_DATE  # 2026-04-15
    # collection 2026-04-01 -> age 14; stored 14 agrees, stored 60 disagrees.
    agree = make_record("E0", collection_date=date(2026, 4, 1), freshness_days=14)
    disagree = make_record("E1", collection_date=date(2026, 4, 1), freshness_days=60)
    finding = checks.freshness_field_consistency([agree, disagree], reference_date=ref)
    assert finding is not None
    assert finding.affected_ids == ["E1"]


def test_freshness_field_consistency_silent_within_tolerance():
    ref = checks.REFERENCE_DATE
    within = make_record("E0", collection_date=date(2026, 4, 1), freshness_days=20)  # age 14, drift 6 <= 7
    assert checks.freshness_field_consistency([within], reference_date=ref) is None


def test_duplicate_evidence_ids():
    records = [make_record("DUP"), make_record("DUP"), make_record("UNIQ")]
    finding = checks.duplicate_evidence_ids(records)
    assert finding is not None
    assert finding.affected_ids == ["DUP"]
    assert finding.affected_count == 2


def test_duplicate_evidence_ids_silent_when_unique():
    records = [make_record("A"), make_record("B")]
    assert checks.duplicate_evidence_ids(records) is None


def test_out_of_range_confidence():
    over = make_record("E0", confidence_score=1.5)
    under = make_record("E1", confidence_score=-0.2)
    ok = make_record("E2", confidence_score=0.8)
    finding = checks.out_of_range_confidence([over, under, ok])
    assert finding is not None
    assert set(finding.affected_ids) == {"E0", "E1"}


def test_out_of_range_confidence_silent_when_in_range():
    assert checks.out_of_range_confidence([make_record("E0", confidence_score=0.5)]) is None


def test_null_or_malformed_dates_via_from_row():
    # blank collection_date and a malformed review_date both flag the row.
    rec = EvidenceRecord.from_row(
        {
            "evidence_id": "E0",
            "requirement_id": "REQ1",
            "requirement_description": "d",
            "framework": "GDPR",
            "evidence_type": "config",
            "collected_by": "t",
            "collector_email": "t@c.com",
            "collection_date": "",
            "freshness_days": "10",
            "evidence_summary": "s",
            "reviewed_by": "r",
            "reviewer_email": "r@c.com",
            "review_date": "not-a-date",
            "evidence_location": "V/1",
            "confidence_score": "0.7",
            "status": "Approved",
            "anomaly_marker": "",
        }
    )
    assert rec.collection_date is None
    assert rec.review_date is None
    assert rec.present_but_unparsed_dates == ["review_date"]
    finding = checks.null_or_malformed_dates([rec])
    assert finding is not None
    assert finding.affected_ids == ["E0"]


def test_null_or_malformed_dates_silent_when_clean():
    assert checks.null_or_malformed_dates([make_record("E0")]) is None


def test_audit_corpus_returns_only_fired_checks():
    # All defaults are clean except a single duplicated description pair.
    records = [make_record("E0", requirement_description="x"), make_record("E1", requirement_description="x")]
    findings = checks.audit_corpus(records, REQS)
    names = {f.check_name for f in findings}
    # duplicate_description fires (2/2 share); orphans do not (R1 is known).
    assert "duplicate_description" in names
    assert "orphan_requirement_refs" not in names
