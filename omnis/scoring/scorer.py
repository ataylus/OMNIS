"""Per-requirement compliance scoring plus the headline roll-ups.

STATUS SEMANTICS (exact):
  COMPLIANT  at least one mapped evidence record that is approved, fresh (per the
             freshness model and the requirement's audit frequency), and
             confident, and none affirmatively failing.
  GAP        mapped evidence affirmatively failing (rejected, stale without
             approval, or contradicted) and no good evidence to offset it.
  PARTIAL    mixed signals: some good evidence and some failing, or only
             ambiguous evidence (pending / needs-update, neither good nor failing).
  UNKNOWN    no mapped evidence at all. This is the "missing evidence" edge case;
             the rationale says so plainly.

A record is "good" when approved AND fresh AND confident; "failing" when rejected
OR (stale AND not approved) OR contradicted (approved but confidence below the
threshold). Freshness uses the requirement's audit frequency to size the window.

OMNISCIENCE INDEX (0-100): mean over requirements of a weighted composite of
three per-requirement components, each in 0..1:
  coverage_r   = 1 if the requirement has any mapped evidence else 0
  freshness_r  = best freshness_score among mapped evidence (0 if none)
  confidence_r = best confidence_score among mapped evidence (0 if none)
  quality_r    = W_COVERAGE*coverage_r + W_FRESHNESS*freshness_r + W_CONFIDENCE*confidence_r
  index        = 100 * mean(quality_r)
Weights 0.4 / 0.3 / 0.3. Rationale: coverage is weighted highest because a
requirement with no evidence cannot pass an audit at all (the system's core
philosophy is to quantify what it does not know); among covered requirements,
how recent the evidence is and how confident it is matter equally. freshness_r
and confidence_r are zero when uncovered, so an uncovered requirement contributes
nothing, and the index degrades gracefully toward 0 as coverage drops.

AUTOMATION RATE: share of evidence records whose evidence_type is machine
collectable (see AUTO_TYPES). It is an official success criterion (target 70%+).
"""

from __future__ import annotations

from omnis.freshness import freshness_score, is_stale, record_age_days
from omnis.models import (
    ComplianceSummary,
    EvidenceLink,
    EvidenceRecord,
    Requirement,
    RequirementScore,
)

CONFIDENCE_THRESHOLD = 0.6

W_COVERAGE = 0.4
W_FRESHNESS = 0.3
W_CONFIDENCE = 0.3

# Evidence types that a system can export without a human in the loop. Config
# snapshots, logs, access/test reports and certificate queries come straight from
# control systems (CloudTrail, AWS Config, IAM, scanners); screenshots, training
# records, written procedures and policy documents are produced by people.
AUTO_TYPES = {
    "Configuration_Snapshot",
    "Audit_Log",
    "Access_Report",
    "Test_Result",
    "Encryption_Cert",
}
MANUAL_TYPES = {
    "Screenshot",
    "Training_Record",
    "Policy_Document",
    "Procedure_Evidence",
}


def _is_good(record: EvidenceRecord, frequency: str | None) -> bool:
    age = record_age_days(record)
    fresh = not is_stale(age, frequency=frequency)
    confident = record.confidence_score is not None and record.confidence_score >= CONFIDENCE_THRESHOLD
    return record.status == "Approved" and fresh and confident


def _is_failing(record: EvidenceRecord, frequency: str | None) -> bool:
    age = record_age_days(record)
    stale = is_stale(age, frequency=frequency)
    if record.status == "Rejected":
        return True
    if stale and record.status != "Approved":
        return True
    # Contradiction: accepted on paper but confidence undermines it.
    if (
        record.status == "Approved"
        and record.confidence_score is not None
        and record.confidence_score < CONFIDENCE_THRESHOLD
    ):
        return True
    return False


def _trust(record: EvidenceRecord, frequency: str | None) -> float:
    age = record_age_days(record)
    conf = record.confidence_score if record.confidence_score is not None else 0.0
    return conf * freshness_score(age, frequency=frequency)


def classify_evidence(
    requirement: Requirement, records: list[EvidenceRecord]
) -> tuple[list[EvidenceRecord], list[EvidenceRecord], list[EvidenceRecord]]:
    """Split mapped records into (good, failing, ambiguous) for a requirement.

    The three buckets are mutually exclusive: good requires approved + fresh +
    confident; failing requires rejected, stale-without-approval, or contradicted;
    ambiguous is everything else (for example pending review or needs update).
    """
    freq = requirement.audit_frequency
    good = [r for r in records if _is_good(r, freq)]
    failing = [r for r in records if _is_failing(r, freq)]
    classified = {id(r) for r in good} | {id(r) for r in failing}
    ambiguous = [r for r in records if id(r) not in classified]
    return good, failing, ambiguous


def score_requirement(
    requirement: Requirement,
    records: list[EvidenceRecord],
) -> RequirementScore:
    """Derive one requirement's status from its mapped evidence records."""
    if not records:
        return RequirementScore(
            requirement_id=requirement.id,
            status="UNKNOWN",
            confidence=0.0,
            evidence_ids=[],
            rationale="No mapped evidence. This requirement is unproven (missing evidence).",
        )

    freq = requirement.audit_frequency
    good, failing, _ambiguous = classify_evidence(requirement, records)
    evidence_ids = [r.evidence_id for r in records]

    if good and not failing:
        status = "COMPLIANT"
        confidence = max(_trust(r, freq) for r in good)
        rationale = f"{len(good)} approved, fresh, confident record(s); none failing."
    elif failing and not good:
        status = "GAP"
        confidence = max(_trust(r, freq) for r in failing) if failing else 0.0
        rationale = f"{len(failing)} record(s) affirmatively failing (rejected / stale / contradicted); no good evidence."
    else:
        status = "PARTIAL"
        confidence = sum(_trust(r, freq) for r in records) / len(records)
        rationale = (
            f"Mixed signals: {len(good)} good, {len(failing)} failing, "
            f"{len(records) - len(good) - len(failing)} ambiguous record(s)."
        )

    return RequirementScore(
        requirement_id=requirement.id,
        status=status,
        confidence=round(confidence, 3),
        evidence_ids=evidence_ids,
        rationale=rationale,
    )


def _coverage_components(
    records: list[EvidenceRecord], frequency: str | None
) -> tuple[float, float, float]:
    if not records:
        return 0.0, 0.0, 0.0
    freshness_r = max(freshness_score(record_age_days(r), frequency=frequency) for r in records)
    confidence_r = max((r.confidence_score or 0.0) for r in records)
    return 1.0, freshness_r, confidence_r


def omniscience_index(
    requirements: list[Requirement],
    mapped_by_requirement: dict[str, list[EvidenceRecord]],
) -> float:
    """0-100 weighted composite of coverage x freshness x confidence."""
    if not requirements:
        return 0.0
    total = 0.0
    for req in requirements:
        records = mapped_by_requirement.get(req.id, [])
        coverage_r, freshness_r, confidence_r = _coverage_components(records, req.audit_frequency)
        total += W_COVERAGE * coverage_r + W_FRESHNESS * freshness_r + W_CONFIDENCE * confidence_r
    return round(100.0 * total / len(requirements), 1)


def automation_rate(records: list[EvidenceRecord]) -> float:
    """Percentage of evidence records that are machine-collectable (AUTO_TYPES)."""
    if not records:
        return 0.0
    automated = sum(1 for r in records if r.evidence_type in AUTO_TYPES)
    return round(100.0 * automated / len(records), 1)


def mapped_records_by_requirement(
    requirements: list[Requirement],
    records: list[EvidenceRecord],
    links: list[EvidenceLink],
) -> tuple[dict[str, list[EvidenceRecord]], dict[str, int], int]:
    """Resolve links into per-requirement record lists.

    Returns (mapped_by_requirement, method_breakdown, unmapped_count). Shared by
    scoring, narrative, and reporting so they agree on which evidence supports
    which requirement.
    """
    by_evidence = {r.evidence_id: r for r in records}
    mapped_by_requirement: dict[str, list[EvidenceRecord]] = {req.id: [] for req in requirements}
    method_breakdown: dict[str, int] = {}
    unmapped_count = 0
    for link in links:
        method_breakdown[link.method] = method_breakdown.get(link.method, 0) + 1
        if not link.mapped or link.requirement_id is None:
            unmapped_count += 1
            continue
        record = by_evidence.get(link.evidence_id)
        if record is not None and link.requirement_id in mapped_by_requirement:
            mapped_by_requirement[link.requirement_id].append(record)
    return mapped_by_requirement, method_breakdown, unmapped_count


def score_corpus(
    requirements: list[Requirement],
    records: list[EvidenceRecord],
    links: list[EvidenceLink],
) -> tuple[list[RequirementScore], ComplianceSummary]:
    """Map links to requirements, score each requirement, and roll up summaries."""
    mapped_by_requirement, method_breakdown, unmapped_count = mapped_records_by_requirement(
        requirements, records, links
    )

    scores = [
        score_requirement(req, mapped_by_requirement[req.id]) for req in requirements
    ]
    status_breakdown: dict[str, int] = {}
    for s in scores:
        status_breakdown[s.status] = status_breakdown.get(s.status, 0) + 1

    summary = ComplianceSummary(
        omniscience_index=omniscience_index(requirements, mapped_by_requirement),
        automation_rate=automation_rate(records),
        total_requirements=len(requirements),
        total_evidence=len(records),
        unmapped_count=unmapped_count,
        status_breakdown=status_breakdown,
        method_breakdown=method_breakdown,
    )
    return scores, summary
