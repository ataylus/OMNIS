# The four judged edge cases

The brief calls out four evidence situations an auditor's tool must handle and
show, not hide: missing, conflicting, low-confidence, and ambiguous evidence.
Each one has a named handling path in OMNIS and a place a judge can see it. The
sections below give the definition, the code that handles it, where it surfaces
(module plus CLI / report / dashboard), and a concrete example from the data.

All status logic lives in `omnis/scoring/scorer.py`; the auditor-voice prose for
each case lives in `omnis/narrative/templates.py`.

## 1. Missing evidence

**Definition.** A requirement has no evidence mapped to it at all. It cannot be
proven either way.

**How OMNIS handles it.** `score_requirement` (scorer.py) returns status
`UNKNOWN` with confidence 0.0 and the rationale "No mapped evidence. This
requirement is unproven (missing evidence)." UNKNOWN is a first-class status, not
an error, so a gap in coverage pulls the Omniscience Index down (coverage is the
0.4-weighted component) instead of being silently skipped.

**Where it surfaces.**
- CLI: `python -m omnis score` and `omnis run` print the UNKNOWN count in the
  status breakdown and the per-requirement rationale.
- Report: the requirement's section in `report.json` / `report.pdf` shows status
  UNKNOWN and the missing-evidence narrative.
- Dashboard: a grey `UNKNOWN` chip on the requirement, and the ask box maps the
  word "missing" to the UNKNOWN status (`STATUS_KEYWORDS` in
  `omnis/dashboard/payload.py`).

**Concrete example.** On the provided sample, `POL-ENC-001-R3`, `POL-AC-001-R1`,
and `POL-AC-001-R3` are UNKNOWN: no evidence row maps to them, so they are
reported as unproven.

## 2. Conflicting evidence

**Definition.** A requirement has both supporting evidence (approved, fresh,
confident) and contradicting evidence (rejected, stale, or contradicted) at the
same time.

**How OMNIS handles it.** `classify_evidence` (scorer.py) splits a requirement's
records into good / failing / ambiguous. When both good and failing are present
the requirement is `PARTIAL`, and the narrative writes the conflict out
explicitly: "The evidence conflicts. N record(s) support the control ... an
auditor cannot rely on conflicting evidence without reconciliation."

**Where it surfaces.**
- CLI: `omnis score` rationale reads "Mixed signals: G good, F failing, A
  ambiguous record(s)."
- Report / dashboard: the conflicting-evidence narrative paragraph, plus a
  `PARTIAL` chip. The ask box maps "conflict" / "conflicting" to PARTIAL.

**Concrete example.** On the provided sample, `POL-ENC-001-R2` is PARTIAL with 2
good and 9 failing records: real support exists, but it is outweighed and
unreconciled.

## 3. Low-confidence evidence

**Definition.** Evidence that is accepted on paper but carries a confidence score
below the 0.6 threshold, so its status and its confidence disagree.

**How OMNIS handles it.** Two paths catch it. (a) The integrity auditor
(`omnis/integrity/checks.py`) raises `status_confidence_contradiction` for rows
marked Approved with confidence < 0.6. (b) In scoring, `_is_failing` treats an
Approved-but-low-confidence row as a contradiction, so it counts against the
requirement rather than for it, and the narrative names low confidence as the
dominant problem when that is what it sees.

**Where it surfaces.**
- CLI: `omnis run` prints the `status_confidence_contradiction` finding with its
  affected count and sample ids.
- Report: the same finding appears in the integrity appendix; affected
  requirements show the low-confidence narrative.
- Dashboard: the finding is listed in the integrity panel.

**Concrete example.** On the provided sample, 18 rows are Approved with
confidence below 0.6. `EVD00001` is one of them (Approved, confidence 0.57): the
paperwork says yes, the confidence says do not trust it.

## 4. Ambiguous evidence

**Definition.** Evidence that is neither clearly good nor clearly failing, for
example pending review or flagged as needs-update.

**How OMNIS handles it.** `classify_evidence` puts these records in the
`ambiguous` bucket (everything not good and not failing). A requirement whose
mapped evidence is only ambiguous is `PARTIAL` with the rationale spelling out
the ambiguous count, and the narrative says the evidence is "present but
inconclusive". The anomaly detector also has a dedicated `UNREVIEWED_EVIDENCE`
class for Pending_Review rows.

**Where it surfaces.**
- CLI: the `omnis score` rationale always reports the ambiguous count alongside
  good and failing; `omnis eval` scores the `UNREVIEWED_EVIDENCE` class
  separately in its per-class table.
- Report / dashboard: the inconclusive-evidence narrative on the requirement.

**Concrete example.** On the provided sample, `POL-AUD-001-R3` is PARTIAL with 75
records in the ambiguous bucket: a large pile of evidence that does not actually
settle the question.

## Summary

| Edge case | Status path | Named handler | Visible in |
|---|---|---|---|
| Missing | UNKNOWN | `score_requirement` | CLI, report, dashboard chip + ask box |
| Conflicting | PARTIAL (good + failing) | `classify_evidence` + narrative | CLI rationale, report/dashboard narrative |
| Low-confidence | contradiction | `status_confidence_contradiction`, `_is_failing` | CLI run, report integrity appendix, dashboard panel |
| Ambiguous | PARTIAL (ambiguous bucket) | `classify_evidence`, `UNREVIEWED_EVIDENCE` | CLI rationale, eval per-class, report/dashboard narrative |
