"""Dashboard data: build the JSON payload and the ask-box filter.

The dashboard reuses the exact pipeline the CLI uses (mapping -> scoring ->
narrative -> integrity audit), so the page never invents numbers. Everything here
is plain data: build_dashboard_data() returns one payload per bench, and
filter_requirements() is the small, documented query logic behind the ask box.
"""

from __future__ import annotations

from pathlib import Path

from omnis.freshness import REFERENCE_DATE, is_stale, record_age_days, staleness_window
from omnis.ingest import parse_policies
from omnis.integrity import audit_corpus
from omnis.mapping import map_evidence
from omnis.models import EvidenceRecord, Requirement
from omnis.narrative import generate_narrative
from omnis.scoring import mapped_records_by_requirement, score_corpus
from omnis.synthesis import load_synthetic_bench

DEFAULT_POLICIES = Path("data/sample/policy_documents.txt")
DEFAULT_EVIDENCE = Path("data/sample/evidence_artifacts.csv")
SYNTHETIC_CSV = Path("data/synthetic/evidence_artifacts.csv")
SYNTHETIC_IDS = Path("data/synthetic/valid_requirement_ids.txt")

# Query words that select a status, mapped to the canonical status. Anything else
# in the query is treated as a free-text term.
STATUS_KEYWORDS = {
    "gap": "GAP",
    "gaps": "GAP",
    "compliant": "COMPLIANT",
    "pass": "COMPLIANT",
    "passing": "COMPLIANT",
    "partial": "PARTIAL",
    "conflict": "PARTIAL",
    "conflicting": "PARTIAL",
    "unknown": "UNKNOWN",
    "missing": "UNKNOWN",
}
# Noise words ignored in the free-text part of a query.
_QUERY_STOPWORDS = {
    "show", "me", "all", "the", "with", "for", "requirements", "requirement",
    "evidence", "status", "find", "list", "of", "a", "is", "are",
}


def _requirement_block(
    requirement: Requirement, score, records: list[EvidenceRecord]
) -> dict:
    ages = [a for a in (record_age_days(r) for r in records) if a is not None]
    stale = sum(1 for r in records if is_stale(record_age_days(r), frequency=requirement.audit_frequency))
    return {
        "requirement_id": requirement.id,
        "policy_title": requirement.policy_title,
        "text": requirement.text,
        "status": score.status,
        "confidence": score.confidence,
        "evidence_count": len(score.evidence_ids),
        "evidence_ids": score.evidence_ids,
        "rationale": score.rationale,
        "narrative": generate_narrative(requirement, score, records),
        "freshness": {
            "window_days": staleness_window(requirement.audit_frequency),
            "min_age_days": min(ages) if ages else None,
            "max_age_days": max(ages) if ages else None,
            "stale_count": stale,
        },
    }


def build_payload(
    bench_label: str,
    requirements: list[Requirement],
    records: list[EvidenceRecord],
) -> dict:
    """Assemble one bench's dashboard payload from loaded requirements + records."""
    links = map_evidence(records, requirements)
    findings = audit_corpus(records, requirements)
    mapped_by_req, _methods, _unmapped = mapped_records_by_requirement(
        requirements, records, links
    )
    scores, summary = score_corpus(requirements, records, links)
    by_id = {s.requirement_id: s for s in scores}

    return {
        "bench": bench_label,
        "generated": REFERENCE_DATE.isoformat(),
        "summary": {
            "omniscience_index": summary.omniscience_index,
            "automation_rate": summary.automation_rate,
            "total_requirements": summary.total_requirements,
            "total_evidence": summary.total_evidence,
            "unmapped_count": summary.unmapped_count,
            "status_breakdown": summary.status_breakdown,
        },
        "requirements": [
            _requirement_block(req, by_id[req.id], mapped_by_req[req.id])
            for req in requirements
        ],
        "integrity_findings": [
            {
                "check_name": f.check_name,
                "severity": f.severity,
                "affected_count": f.affected_count,
                "description": f.description,
            }
            for f in findings
        ],
    }


def build_dashboard_data(policies: Path = DEFAULT_POLICIES) -> dict:
    """Build payloads for both benches: {"sample": {...}, "synthetic": {...}|None}."""
    requirements = parse_policies(policies)
    sample_records = load_evidence_safe(DEFAULT_EVIDENCE)
    data = {"sample": build_payload("provided sample", requirements, sample_records)}
    if SYNTHETIC_CSV.exists() and SYNTHETIC_IDS.exists():
        syn_records, _ = load_synthetic_bench(SYNTHETIC_CSV, SYNTHETIC_IDS)
        data["synthetic"] = build_payload("synthetic", requirements, syn_records)
    else:
        data["synthetic"] = None
    return data


def load_evidence_safe(path: Path) -> list[EvidenceRecord]:
    from omnis.models import load_evidence

    return load_evidence(path)


def filter_requirements(requirements: list[dict], query: str) -> list[dict]:
    """Filter requirement blocks by a plain-text query.

    Logic (deliberately simple and local, no LLM):
      1. Lowercase the query and split into words.
      2. Words that name a status (gap, unknown, partial, compliant, and a few
         synonyms) become status filters; a requirement passes if its status is
         among them.
      3. Remaining words (minus stopwords) are free-text terms; a requirement
         passes if every term is a substring of its searchable text (id, policy,
         requirement text, status, rationale, narrative, evidence ids).
      4. An empty query returns everything.
    """
    q = (query or "").strip().lower()
    if not q:
        return list(requirements)

    words = [w for w in q.replace(",", " ").split() if w]
    statuses = {STATUS_KEYWORDS[w] for w in words if w in STATUS_KEYWORDS}
    terms = [w for w in words if w not in STATUS_KEYWORDS and w not in _QUERY_STOPWORDS]

    def matches(req: dict) -> bool:
        if statuses and req["status"] not in statuses:
            return False
        if terms:
            blob = " ".join(
                [
                    req["requirement_id"],
                    req["policy_title"],
                    req["text"],
                    req["status"],
                    req["rationale"],
                    req["narrative"],
                    " ".join(req["evidence_ids"]),
                ]
            ).lower()
            if not all(term in blob for term in terms):
                return False
        return True

    return [req for req in requirements if matches(req)]
