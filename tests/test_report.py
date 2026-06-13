"""Tests for the report generator: JSON keys and a non-empty PDF."""

from datetime import date

from omnis.ingest import parse_policies
from omnis.integrity import audit_corpus
from omnis.mapping import map_evidence
from omnis.models import EvidenceRecord
from omnis.report import build_report, render_pdf, write_report

REQUIREMENTS = parse_policies("data/sample/policy_documents.txt")


def ev(evidence_id, requirement_id, status="Approved", freshness_days=5, confidence=0.9):
    return EvidenceRecord(
        evidence_id=evidence_id,
        requirement_id=requirement_id,
        requirement_description="Data access must be logged and reviewed",
        framework="GDPR",
        evidence_type="Audit_Log",
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 4, 1),
        freshness_days=freshness_days,
        evidence_summary="audit log review",
        status=status,
        confidence_score=confidence,
    )


def _report():
    records = [
        ev("E1", "POL-AUD-001-R1", status="Approved", confidence=0.95),
        ev("E2", "POL-AUD-001-R1", status="Rejected"),
        ev("E3", "POL-ENC-001-R1", status="Approved", confidence=0.5),
    ]
    links = map_evidence(records, REQUIREMENTS)
    findings = audit_corpus(records, REQUIREMENTS)
    return build_report("test bench", REQUIREMENTS, records, links, findings), records


def test_report_json_has_expected_keys():
    report, _records = _report()
    for key in ("title", "bench", "generated", "executive_summary", "requirements", "integrity_findings"):
        assert key in report
    es = report["executive_summary"]
    for key in ("omniscience_index", "automation_rate", "total_requirements", "status_breakdown"):
        assert key in es
    assert len(report["requirements"]) == len(REQUIREMENTS)
    first = report["requirements"][0]
    for key in ("requirement_id", "status", "confidence", "evidence_ids", "freshness", "narrative", "next_steps"):
        assert key in first
    assert report["generated"] == "2026-04-15"  # REFERENCE_DATE


def test_render_pdf_is_non_empty(tmp_path):
    report, _records = _report()
    path = render_pdf(report, tmp_path / "report.pdf")
    assert path.exists()
    data = path.read_bytes()
    assert len(data) > 1000
    assert data[:4] == b"%PDF"


def test_write_report_writes_both_files(tmp_path):
    report, _records = _report()
    json_path, pdf_path = write_report(report, tmp_path)
    assert json_path.exists() and pdf_path.exists()
    assert json_path.read_text(encoding="utf-8").strip().startswith("{")
    assert pdf_path.stat().st_size > 1000
