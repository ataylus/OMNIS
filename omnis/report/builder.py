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
                "frameworks": ", ".join(req.compliance_mappings[:2]) or "n/a",
                "ambiguous": req.ambiguous,
                "ambiguity_note": req.ambiguity_note,
                "status": score.status,
                "confidence": score.confidence,
                "evidence_ids": score.evidence_ids,
                "freshness": _freshness_block(req, mapped),
                "narrative": generate_narrative(req, score, mapped, enrich=enrich),
                "next_steps": recommend(req, score, mapped),
                "evidence": [
                    {
                        "evidence_id": r.evidence_id,
                        "evidence_type": r.evidence_type,
                        "location": r.evidence_location or "n/a",
                        "status": r.status,
                    }
                    for r in mapped[:4]
                ],
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


# Near-black ink and quiet greys for a printed-document feel. Status colors are
# the dashboard's, so the report and the UI read as one product.
INK = (26, 25, 23)
MUTED = (120, 116, 108)
LINE = (200, 196, 188)

# status name -> (strong, soft) and severity -> (strong, soft)
_STATUS_COLORS = {
    "COMPLIANT": ((31, 122, 77), (233, 244, 238)),
    "PARTIAL": ((154, 91, 8), (251, 240, 220)),
    "GAP": ((179, 38, 30), (251, 233, 232)),
    "UNKNOWN": ((95, 107, 122), (238, 241, 245)),
}
_STATUS_ORDER = ["COMPLIANT", "PARTIAL", "GAP", "UNKNOWN"]
_SEVERITY_COLORS = {
    "HIGH": _STATUS_COLORS["GAP"],
    "CRITICAL": _STATUS_COLORS["GAP"],
    "MEDIUM": _STATUS_COLORS["PARTIAL"],
    "LOW": _STATUS_COLORS["UNKNOWN"],
}


FONT_DIR = Path(__file__).parent / "fonts"


class _ReportPDF(FPDF):
    """A typeset compliance report in the manner of a LaTeX article: Latin Modern
    (Computer Modern) serif body, a centered title block, an abstract, numbered
    sections, a booktabs-style summary table, justified text, and a captioned
    figure. A small amount of color marks compliance status; the rest is black."""

    fam = "Times"  # swapped for the embedded Latin Modern family when it loads

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_xy(self.l_margin, 12)
        self.set_font(self.fam, "I", 8.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _latin1("OMNIS  Compliance Evidence Report"))
        self.cell(0, 5, _latin1(self._bench_line), align="R")
        self._hrule(18, color=LINE, width=0.2)
        self.set_y(25)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font(self.fam, "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, _latin1("Ansh Jain  |  github.com/ataylus"), align="L",
                  new_x=XPos.LEFT, new_y=YPos.TOP)
        self.set_font(self.fam, "", 9.5)
        self.set_text_color(*INK)
        self.cell(0, 6, _latin1(str(self.page_no())), align="C")

    # --- drawing helpers -------------------------------------------------

    def _hrule(self, y: float, color=INK, width: float = 0.2, x0=None, x1=None) -> None:
        self.set_draw_color(*color)
        self.set_line_width(width)
        x0 = self.l_margin if x0 is None else x0
        x1 = (self.w - self.r_margin) if x1 is None else x1
        self.line(x0, y, x1, y)

    def _section(self, number: str, title: str) -> None:
        if self.get_y() > self.h - 40:
            self.add_page()
        self.ln(2)
        self.set_font(self.fam, "B", 13)
        self.set_text_color(*INK)
        self.cell(0, 7, _latin1(f"{number}   {title}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)

    def _segmented_bar(self, x: float, y: float, w: float, h: float, segments: list) -> None:
        """segments: list of (count, rgb). A thin distribution bar."""
        total = sum(c for c, _ in segments) or 1
        cx = x
        gap = 0.7
        for i, (count, rgb) in enumerate(segments):
            seg_w = w * count / total
            if seg_w <= 0:
                continue
            draw_w = seg_w - (gap if i < len(segments) - 1 else 0)
            self.set_fill_color(*rgb)
            self.rect(cx, y, max(draw_w, 0.5), h, style="F")
            cx += seg_w


def _booktabs(pdf: _ReportPDF, x: float, w: float, rows: list) -> None:
    """A LaTeX booktabs-style table: thick top and bottom rules, a thin rule under
    the header, no vertical lines."""
    fam = pdf.fam
    c1 = w * 0.62
    c2 = w - c1
    y = pdf.get_y()
    pdf._hrule(y, INK, 0.5, x, x + w)
    y += 1.6
    pdf.set_xy(x, y)
    pdf.set_font(fam, "B", 10)
    pdf.set_text_color(*INK)
    pdf.cell(c1, 6, _latin1("Metric"))
    pdf.cell(c2, 6, _latin1("Value"), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    y = pdf.get_y() + 0.4
    pdf._hrule(y, INK, 0.25, x, x + w)
    y += 1.6
    for key, value in rows:
        pdf.set_xy(x, y)
        pdf.set_font(fam, "", 10)
        pdf.cell(c1, 5.8, _latin1(key))
        pdf.set_font(fam, "B", 10)
        pdf.cell(c2, 5.8, _latin1(value), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        y = pdf.get_y()
    y += 0.6
    pdf._hrule(y, INK, 0.5, x, x + w)
    pdf.set_y(y + 3)


def render_pdf(report: dict, path: str | Path) -> Path:
    """Render the report dictionary to a typeset PDF file and return its path."""
    pdf = _ReportPDF()
    pdf._generated = report["generated"]
    pdf._bench_line = f"{report['bench']} bench"
    try:
        pdf.add_font("LMRoman", "", str(FONT_DIR / "lmroman10-regular.otf"))
        pdf.add_font("LMRoman", "B", str(FONT_DIR / "lmroman10-bold.otf"))
        pdf.add_font("LMRoman", "I", str(FONT_DIR / "lmroman10-italic.otf"))
        pdf.fam = "LMRoman"
    except Exception:
        pdf.fam = "Times"  # core serif fallback so the engine never breaks offline
    fam = pdf.fam

    pdf.set_margins(24, 22, 24)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    left = pdf.l_margin
    right = pdf.w - pdf.r_margin
    width = right - left
    es = report["executive_summary"]
    sb = es["status_breakdown"]
    idx = es["omniscience_index"]
    nreq = es["total_requirements"]
    status_str = ", ".join(f"{sb[s]} {s.lower()}" for s in _STATUS_ORDER if sb.get(s))

    # --- title block -----------------------------------------------------
    pdf.set_y(28)
    pdf.set_font(fam, "B", 21)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, _latin1("OMNIS Compliance Evidence Report"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.set_font(fam, "I", 11.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, _latin1("the partly omniscient auditor"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)
    pdf.set_font(fam, "", 10)
    pdf.set_text_color(*INK)
    pdf.cell(
        0,
        5,
        _latin1(f"{report['bench']} bench    .    {nreq} requirements    .    generated {report['generated']}"),
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(4)
    pdf._hrule(pdf.get_y(), color=INK, width=0.3, x0=left + 34, x1=right - 34)
    pdf.ln(7)

    # --- abstract --------------------------------------------------------
    pdf.set_font(fam, "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(0, 5, _latin1("Abstract"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)
    abstract = (
        f"OMNIS parsed {nreq} requirements from the {report['bench']} policy set and linked "
        f"{es['total_evidence']} evidence records against them. The Omniscience Index, a weighted "
        f"composite of evidence coverage, freshness, and confidence, is {idx} out of 100, with an "
        f"automation rate of {es['automation_rate']}%. {es['unmapped_count']} evidence records were "
        f"left unmapped. The sections below give the per-requirement compliance status with its "
        f"supporting evidence and freshness, followed by the data-quality findings OMNIS raised "
        f"against the corpus itself."
    )
    indent = 12
    pdf.set_x(left + indent)
    pdf.set_font(fam, "", 9.8)
    pdf.set_text_color(*INK)
    pdf.multi_cell(width - 2 * indent, 5.1, _latin1(abstract), align="J", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # --- 1 executive summary --------------------------------------------
    pdf._section("1", "Executive summary")
    rows = [
        ("Omniscience Index", f"{idx} / 100"),
        ("Automation Rate", f"{es['automation_rate']}%"),
        ("Requirements", str(nreq)),
        ("Evidence records", str(es["total_evidence"])),
        ("Unmapped evidence", str(es["unmapped_count"])),
        ("Status breakdown", status_str or "none"),
    ]
    table_w = 122
    _booktabs(pdf, left + (width - table_w) / 2, table_w, rows)
    pdf.ln(3)

    # figure 1: status distribution, with a caption
    bar_w = 122
    bx = left + (width - bar_w) / 2
    by = pdf.get_y()
    segments = [(sb.get(s, 0), _STATUS_COLORS[s][0]) for s in _STATUS_ORDER]
    pdf._segmented_bar(bx, by, bar_w, 3.4, segments)
    pdf.set_y(by + 5)
    pdf.set_font(fam, "I", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0,
        4.5,
        _latin1(f"Figure 1.  Compliance status across {nreq} requirements ({status_str})."),
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(3)

    # --- 2 traceability matrix ------------------------------------------
    pdf._section("2", "Traceability matrix")
    pdf.set_font(fam, "", 9.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        width,
        4.6,
        _latin1("Every requirement, its compliance mapping, its status, and how many evidence records back it."),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="L",
    )
    pdf.ln(2)
    cols = [("Requirement", 0.24), ("Status", 0.15), ("Evidence", 0.13), ("Compliance mapping", 0.48)]
    y = pdf.get_y()
    pdf._hrule(y, INK, 0.5)
    y += 1.6
    pdf.set_xy(left, y)
    pdf.set_font(fam, "B", 9)
    pdf.set_text_color(*INK)
    for name, frac in cols:
        pdf.cell(width * frac, 5.4, _latin1(name))
    pdf.ln(5.4)
    pdf._hrule(pdf.get_y() + 0.2, INK, 0.25)
    pdf.ln(1.6)
    for r in report["requirements"]:
        if pdf.get_y() > pdf.h - 22:
            pdf.add_page()
        strong, _soft = _STATUS_COLORS.get(r["status"], _STATUS_COLORS["UNKNOWN"])
        rx = left
        pdf.set_font(fam, "", 9)
        pdf.set_text_color(*INK)
        pdf.set_xy(rx, pdf.get_y())
        pdf.cell(width * cols[0][1], 5.2, _latin1(r["requirement_id"]))
        pdf.set_text_color(*strong)
        pdf.set_font(fam, "B", 9)
        pdf.cell(width * cols[1][1], 5.2, _latin1(r["status"]))
        pdf.set_font(fam, "", 9)
        pdf.set_text_color(*INK)
        pdf.cell(width * cols[2][1], 5.2, _latin1(str(len(r["evidence_ids"]))))
        pdf.set_text_color(*MUTED)
        pdf.cell(width * cols[3][1], 5.2, _latin1(r["frameworks"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf._hrule(pdf.get_y() + 0.4, INK, 0.5)
    pdf.ln(4)

    # --- 3 requirements --------------------------------------------------
    pdf._section("3", "Requirements")
    for i, r in enumerate(report["requirements"], start=1):
        if pdf.get_y() > pdf.h - 44:
            pdf.add_page()
        fr = r["freshness"]
        strong, _soft = _STATUS_COLORS.get(r["status"], _STATUS_COLORS["UNKNOWN"])
        # run-in subsection heading: "3.i  REQ-ID   STATUS"
        pdf.set_font(fam, "B", 10.5)
        pdf.set_text_color(*INK)
        head = f"3.{i}   {r['requirement_id']}"
        pdf.cell(pdf.get_string_width(_latin1(head)) + 2.5, 5.6, _latin1(head))
        pdf.set_text_color(*strong)
        pdf.cell(0, 5.6, _latin1(r["status"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # meta line, italic
        pdf.set_font(fam, "I", 9)
        pdf.set_text_color(*MUTED)
        meta = (
            f"{r['policy_title']}.  Confidence {r['confidence']:.2f}.  "
            f"{len(r['evidence_ids'])} evidence records.  "
            f"Stale {fr['stale_count']}/{fr['evidence_count']} (window {fr['window_days']} days)."
        )
        pdf.multi_cell(width, 4.4, _latin1(meta), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="J")
        pdf.ln(1)
        # ambiguous (principle-based) requirements get a flagged note
        if r.get("ambiguous"):
            amber = _STATUS_COLORS["PARTIAL"][0]
            pdf.set_font(fam, "I", 9)
            pdf.set_text_color(*amber)
            pdf.multi_cell(
                width,
                4.4,
                _latin1(f"Ambiguous requirement. {r.get('ambiguity_note', '')}"),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                align="L",
            )
            pdf.ln(1)
        # linked evidence pointers, so a reader can follow the proof to the artifact
        for ev in r.get("evidence", []):
            pdf.set_font(fam, "I", 8.8)
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(
                width,
                4.1,
                _latin1(
                    f"     {ev['evidence_id']}  ·  {ev['evidence_type']}  ·  "
                    f"{ev['status']}  ·  {ev['location']}"
                ),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                align="L",
            )
        if r.get("evidence"):
            pdf.ln(1)
        # narrative, justified
        pdf.set_font(fam, "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(width, 5.0, _latin1(r["narrative"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="J")
        pdf.ln(1)
        # next step, italic run-in label
        prefix = "Next step.  "
        pdf.set_font(fam, "I", 10)
        pdf.set_text_color(*INK)
        pw = pdf.get_string_width(_latin1(prefix))
        pdf.cell(pw, 5.0, _latin1(prefix))
        pdf.set_font(fam, "", 10)
        pdf.multi_cell(width - pw, 5.0, _latin1(r["next_steps"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="J")
        pdf.ln(5)

    # --- 3 corpus integrity findings ------------------------------------
    pdf._section("4", "Corpus integrity findings")
    pdf.set_font(fam, "", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(
        width,
        5.0,
        _latin1(
            "Data-quality issues OMNIS detected in the evidence corpus and reported, rather than "
            "crashed on. Severity reflects audit impact."
        ),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="J",
    )
    pdf.ln(3)
    if not report["integrity_findings"]:
        pdf.cell(0, 5, _latin1("No integrity findings."))
    for i, f in enumerate(report["integrity_findings"], start=1):
        if pdf.get_y() > pdf.h - 32:
            pdf.add_page()
        strong, _soft = _SEVERITY_COLORS.get(f["severity"], _STATUS_COLORS["UNKNOWN"])
        pdf.set_font(fam, "B", 10.5)
        pdf.set_text_color(*INK)
        head = f"4.{i}   {f['check_name']}"
        pdf.cell(pdf.get_string_width(_latin1(head)) + 2.5, 5.6, _latin1(head))
        pdf.set_text_color(*strong)
        pdf.cell(0, 5.6, _latin1(f["severity"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font(fam, "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(
            width,
            5.0,
            _latin1(f"{f['affected_count']} rows. {f['description']}"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align="J",
        )
        pdf.ln(4)

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
