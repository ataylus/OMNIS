"""Audit narrative generation.

The primary path is a deterministic template engine that turns a RequirementScore
plus its linked evidence into auditor-voice prose. It always produces complete,
professional output with no external calls. The four judged edge cases (missing
evidence, conflicting evidence, low-confidence evidence, ambiguous evidence) each
get a visibly distinct narrative so a reader can see the system handling them.

When OMNIS_LLM_MODE is not "off", `generate_narrative(..., enrich=True)` may pass
the template through omnis.llm for a richer rewrite; the template result stands if
the model is unavailable. No prose contains an em dash (project style rule).
"""

from __future__ import annotations

from omnis import llm
from omnis.freshness import (
    is_stale,
    normalize_frequency,
    record_age_days,
    staleness_window,
)
from omnis.models import EvidenceRecord, Requirement, RequirementScore
from omnis.scoring import classify_evidence
from omnis.scoring.scorer import CONFIDENCE_THRESHOLD


def _sanitize(text: str) -> str:
    # Enforce the no-em-dash style rule even on enriched output.
    return text.replace("—", ", ").replace("–", "-")


def _contradicted(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    return [
        r
        for r in records
        if r.status == "Approved"
        and r.confidence_score is not None
        and r.confidence_score < CONFIDENCE_THRESHOLD
    ]


def _freshness_sentence(requirement: Requirement, records: list[EvidenceRecord]) -> str:
    ages = [record_age_days(r) for r in records]
    ages = [a for a in ages if a is not None]
    if not ages:
        return "Evidence ages could not be determined."
    freq = requirement.audit_frequency
    window = staleness_window(freq)
    stale = sum(1 for r in records if is_stale(record_age_days(r), frequency=freq))
    freq_label = (normalize_frequency(freq) or "default").capitalize()
    return (
        f"Evidence age ranges from {min(ages)} to {max(ages)} days. "
        f"{stale} of {len(records)} record(s) fall outside the {window}-day "
        f"{freq_label} freshness window."
    )


def _confidence_sentence(score: RequirementScore, records: list[EvidenceRecord]) -> str:
    confs = [r.confidence_score for r in records if r.confidence_score is not None]
    if not confs:
        return f"Status confidence is {score.confidence:.2f}."
    mean_conf = sum(confs) / len(confs)
    return (
        f"Mean evidence confidence is {mean_conf:.2f}; status confidence is "
        f"{score.confidence:.2f}."
    )


def recommend(requirement: Requirement, score: RequirementScore, records: list[EvidenceRecord]) -> str:
    """A plain next-step recommendation tailored to the status."""
    good, failing, ambiguous = classify_evidence(requirement, records)
    source = requirement.evidence_source or "the responsible control system"
    if score.status == "UNKNOWN":
        return f"Collect and link evidence for this requirement from {source}."
    if score.status == "GAP":
        if _contradicted(records) and len(_contradicted(records)) >= len(failing) / 2:
            return (
                "Re-collect higher-confidence evidence; the current records are "
                "approved but fall below the confidence threshold."
            )
        return "Remediate the failing control and re-collect current, approved evidence."
    if score.status == "PARTIAL":
        if good and failing:
            return "Reconcile the conflicting records and retire the stale or rejected evidence."
        return "Complete the outstanding reviews so the evidence becomes conclusive."
    return "Maintain the current evidence cadence and re-verify at the next audit window."


def generate_narrative(
    requirement: Requirement,
    score: RequirementScore,
    records: list[EvidenceRecord],
    enrich: bool = False,
) -> str:
    """Produce an auditor-voice narrative for one requirement."""
    good, failing, ambiguous = classify_evidence(requirement, records)
    total = len(records)
    header = (
        f"Requirement {requirement.id} ({requirement.policy_title}) requires: "
        f"{requirement.text}."
    )

    if score.status == "UNKNOWN":
        body = (
            "No evidence is currently linked to this requirement. This is a "
            "coverage gap: the control cannot be demonstrated and must be treated "
            "as unproven until evidence is collected."
        )
    elif score.status == "COMPLIANT":
        body = (
            f"The control is supported. {len(good)} of {total} linked record(s) "
            f"are approved, fresh, and confident, and none affirmatively fail. "
            f"{_freshness_sentence(requirement, records)} "
            f"{_confidence_sentence(score, records)}"
        )
    elif score.status == "GAP":
        contradicted = _contradicted(records)
        if contradicted and len(contradicted) >= len(failing) / 2:
            driver = (
                f"The dominant problem is low confidence: {len(contradicted)} "
                f"record(s) are approved but carry confidence below "
                f"{CONFIDENCE_THRESHOLD:.2f}, which undermines their evidentiary value."
            )
        else:
            driver = (
                f"{len(failing)} of {total} record(s) are rejected, stale without "
                f"approval, or contradicted."
            )
        body = (
            f"The linked evidence affirmatively fails to demonstrate the control. "
            f"{driver} {_freshness_sentence(requirement, records)} "
            f"{_confidence_sentence(score, records)}"
        )
    else:  # PARTIAL
        if good and failing:
            body = (
                f"The evidence conflicts. {len(good)} record(s) support the control "
                f"while {len(failing)} contradict it (rejected, stale, or low "
                f"confidence), and {len(ambiguous)} are inconclusive. An auditor "
                f"cannot rely on conflicting evidence without reconciliation. "
                f"{_freshness_sentence(requirement, records)} "
                f"{_confidence_sentence(score, records)}"
            )
        else:
            body = (
                f"Evidence is present but inconclusive. {len(ambiguous)} of {total} "
                f"record(s) are pending review or awaiting update, and neither "
                f"clearly support nor refute the control. "
                f"{_freshness_sentence(requirement, records)} "
                f"{_confidence_sentence(score, records)}"
            )

    next_step = f"Recommended next step: {recommend(requirement, score, records)}"
    narrative = _sanitize(f"{header} {body} {next_step}")

    if enrich and llm.get_mode() != "off":
        prompt = (
            "Rewrite the following compliance audit note in concise, professional "
            "auditor voice. Keep every fact, do not invent evidence, and do not use "
            "an em dash.\n\n" + narrative
        )
        enriched = llm.complete(prompt, purpose="narrative")
        if enriched:
            return _sanitize(enriched.strip())
    return narrative
