"""Auditor-ready report generator: a JSON report and a matching PDF.

Both artifacts cover one bench: an executive summary (Omniscience Index,
Automation Rate, status counts), a per-requirement section (status, confidence,
linked evidence, freshness, narrative, next step), and an appendix of integrity
findings on the corpus. The PDF is plain text laid out with fpdf2, so it stays a
few tens of KB and needs no system fonts or network access.
"""

from __future__ import annotations

import json
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from omnis.freshness import REFERENCE_DATE, is_stale, record_age_days, staleness_window
from omnis.models import EvidenceLink, EvidenceRecord, IntegrityFinding, Requirement
from omnis.narrative import generate_narrative, recommend
from omnis.scoring import mapped_records_by_requirement, score_corpus

TITLE = "OMNIS Compliance Evidence Report"


def _freshness_block(requirement: Requirement, records: list[EvidenceRecord]) -> dict:
    ages = [a for a in (record_age_days(r) for r in records) if a is not None]
    stale = sum(1 for r in records if is_stale(record_age_days(r), frequency=requirement.audit_frequency))
    return {
        "window_days": staleness_window(requirement.audit_frequency),
        "audit_frequency": requirement.audit_frequency,
        "min_age_days": min(ages) if ages else None,
        "max_age_days": max(ages) if ages else None,
        "stale_count": stale,
        "evidence_count": len(records),
    }


def build_report(
    bench_name: str,
    requirements: list[Requirement],
    records: list[EvidenceRecord],
    links: list[EvidenceLink],
    integrity_findings: list[IntegrityFinding],
    enrich: bool = False,
) -> dict:
    """Assemble the machine-readable report dictionary for one bench."""
    mapped_by_req, _methods, _unmapped = mapped_records_by_requirement(
        requirements, records, links
    )
    scores, summary = score_corpus(requirements, records, links)
    by_id = {s.requirement_id: s for s in scores}
    req_by_id = {r.id: r for r in requirements}

    requirement_sections = []
    for req in requirements:
        score = by_id[req.id]
        mapped = mapped_by_req[req.id]
        requirement_sections.append(
            {
                "requirement_id": req.id,
                "policy_title": req.policy_title,
                "text": req.text,
                "status": score.status,
                "confidence": score.confidence,
                "evidence_ids": score.evidence_ids,
                "freshness": _freshness_block(req, mapped),
                "narrative": generate_narrative(req, score, mapped, enrich=enrich),
                "next_steps": recommend(req, score, mapped),
            }
        )

    return {
        "title": TITLE,
        "bench": bench_name,
        "generated": REFERENCE_DATE.isoformat(),
        "executive_summary": {
            "omniscience_index": summary.omniscience_index,
            "automation_rate": summary.automation_rate,
            "total_requirements": summary.total_requirements,
            "total_evidence": summary.total_evidence,
            "unmapped_count": summary.unmapped_count,
            "status_breakdown": summary.status_breakdown,
        },
        "requirements": requirement_sections,
        "integrity_findings": [
            {
                "check_name": f.check_name,
                "severity": f.severity,
                "affected_count": f.affected_count,
                "description": f.description,
            }
            for f in integrity_findings
        ],
    }


def _latin1(text: str) -> str:
    # fpdf2 core fonts are latin-1; our prose is ASCII, but guard anyway.
    return text.encode("latin-1", "replace").decode("latin-1")


class _ReportPDF(FPDF):
    def heading(self, text: str, size: int = 14) -> None:
        self.set_font("Helvetica", "B", size)
        self.multi_cell(0, size * 0.55, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def body(self, text: str, size: int = 10) -> None:
        self.set_font("Helvetica", "", size)
        self.multi_cell(0, size * 0.52, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def render_pdf(report: dict, path: str | Path) -> Path:
    """Render the report dictionary to a PDF file and return its path."""
    pdf = _ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.heading(report["title"], size=18)
    pdf.body(f"Bench: {report['bench']}    Generated: {report['generated']}")
    pdf.ln(3)

    es = report["executive_summary"]
    pdf.heading("Executive summary", size=14)
    pdf.body(
        f"Omniscience Index: {es['omniscience_index']}/100\n"
        f"Automation Rate: {es['automation_rate']}%\n"
        f"Requirements: {es['total_requirements']}    "
        f"Evidence records: {es['total_evidence']}    "
        f"Unmapped: {es['unmapped_count']}\n"
        f"Status breakdown: {es['status_breakdown']}"
    )
    pdf.ln(3)

    pdf.heading("Requirements", size=14)
    for r in report["requirements"]:
        fr = r["freshness"]
        pdf.heading(f"{r['requirement_id']}  [{r['status']}]", size=12)
        pdf.body(
            f"Policy: {r['policy_title']}    Confidence: {r['confidence']:.2f}\n"
            f"Linked evidence: {len(r['evidence_ids'])} record(s)    "
            f"Stale: {fr['stale_count']}/{fr['evidence_count']} "
            f"(window {fr['window_days']}d)"
        )
        pdf.body(r["narrative"])
        pdf.body(f"Next step: {r['next_steps']}")
        pdf.ln(2)

    pdf.add_page()
    pdf.heading("Appendix: corpus integrity findings", size=14)
    if not report["integrity_findings"]:
        pdf.body("No integrity findings.")
    for f in report["integrity_findings"]:
        pdf.heading(f"[{f['severity']}] {f['check_name']} (count {f['affected_count']})", size=11)
        pdf.body(f["description"])
        pdf.ln(1)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return out


def write_report(report: dict, out_dir: str | Path) -> tuple[Path, Path]:
    """Write report.json and report.pdf into out_dir; return both paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    pdf_path = render_pdf(report, out / "report.pdf")
    return json_path, pdf_path
