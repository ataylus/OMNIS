"""Tests for the layered evidence-to-requirement linker."""

from datetime import date

from omnis.ingest import parse_policies
from omnis.mapping import SIM_FLOOR, map_evidence
from omnis.mapping.linker import TfidfIndex
from omnis.models import EvidenceRecord

REQUIREMENTS = parse_policies("data/sample/policy_documents.txt")


def rec(**overrides):
    base = dict(
        evidence_id="E0",
        requirement_id="ORPHAN",
        requirement_description="generic evidence",
        framework="HIPAA",
        evidence_type="Screenshot",
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 4, 1),
        freshness_days=10,
        evidence_summary="",
        status="Approved",
        confidence_score=0.9,
    )
    base.update(overrides)
    return EvidenceRecord(**base)


def link_for(record):
    return map_evidence([record], REQUIREMENTS)[0]


def test_layer_a_exact_id():
    link = link_for(rec(requirement_id="POL-ENC-001-R1"))
    assert link.method == "exact_id"
    assert link.requirement_id == "POL-ENC-001-R1"
    assert link.confidence == 1.0
    assert link.mapped is True


def test_layer_b_framework_rule():
    # Orphan id (exact fails); GDPR framework + Audit_Log type overlaps the audit
    # logging requirement's evidence_source ("... Database Audit Trails").
    link = link_for(
        rec(
            requirement_id="ORPHAN",
            framework="GDPR",
            evidence_type="Audit_Log",
            requirement_description="",  # keep tfidf from firing first anyway
        )
    )
    assert link.method == "framework_rule"
    assert link.requirement_id == "POL-AUD-001-R1"
    assert 0.55 <= link.confidence <= 0.8
    assert link.mapped is True


def test_layer_c_tfidf_semantic():
    # Orphan id; HIPAA matches no requirement framework (skips rule layer); the
    # shared description carries the semantic signal to the audit-logging policy.
    link = link_for(
        rec(
            requirement_id="ORPHAN",
            framework="HIPAA",
            evidence_type="Test_Result",  # neutral tokens; description carries the signal
            requirement_description="Data access must be logged and reviewed",
            evidence_summary="",
        )
    )
    assert link.method == "tfidf"
    assert link.requirement_id.startswith("POL-AUD-001")
    assert link.confidence >= SIM_FLOOR
    assert link.mapped is True


def test_unmapped_below_floor():
    link = link_for(
        rec(
            requirement_id="ORPHAN",
            framework="Nonsense",
            evidence_type="Quux",
            requirement_description="zzzqqq xyzzy wibble",
            evidence_summary="frobnicate the foobar",
        )
    )
    assert link.method == "unmapped"
    assert link.requirement_id is None
    assert link.mapped is False
    assert link.confidence < SIM_FLOOR


def test_shared_description_lands_on_audit_logging_requirement():
    # The user-specified verification: the sample's shared description, on its own,
    # semantically lands on POL-AUD-001-R1 with moderate confidence.
    index = TfidfIndex(REQUIREMENTS)
    idx, sim = index.best_match("Data access must be logged and reviewed")
    assert REQUIREMENTS[idx].id == "POL-AUD-001-R1"
    assert 0.2 <= sim <= 0.6  # moderate
