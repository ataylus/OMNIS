"""Typed domain objects for OMNIS.

Every object the pipeline passes around is defined here as a pydantic model so
that field names, types, and validation live in one place. The evidence loader
is deliberately lenient: malformed dates and out-of-range numbers become None
rather than raising, because detecting those defects is the integrity auditor's
job (the data is known to contain them on purpose).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, field_validator

# The 17 columns of evidence_artifacts.csv, in file order. Used by the loader
# and asserted against the CSV header so a schema drift fails loudly.
EVIDENCE_COLUMNS: tuple[str, ...] = (
    "evidence_id",
    "requirement_id",
    "requirement_description",
    "framework",
    "evidence_type",
    "collected_by",
    "collector_email",
    "collection_date",
    "freshness_days",
    "evidence_summary",
    "reviewed_by",
    "reviewer_email",
    "review_date",
    "evidence_location",
    "confidence_score",
    "status",
    "anomaly_marker",
)

SEVERITIES: tuple[str, ...] = ("INFO", "LOW", "MEDIUM", "HIGH")


def _parse_date(value: Any) -> date | None:
    """Parse an ISO date string, returning None for blank or unparseable input."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class Requirement(BaseModel):
    """One testable requirement extracted from a policy document."""

    id: str
    policy_id: str
    policy_title: str
    number: int
    text: str
    responsible: str | None = None
    scope: str | None = None
    evidence_source: str | None = None
    audit_frequency: str | None = None
    compliance_mappings: list[str] = []
    # Set by the parser: a principle-based requirement with no measurable
    # threshold (e.g. "least privilege"), so compliance needs auditor judgment.
    ambiguous: bool = False
    ambiguity_note: str | None = None
    # Passthrough policy header context.
    policy_version: str | None = None
    policy_status: str | None = None
    policy_last_updated: date | None = None


class EvidenceRecord(BaseModel):
    """One collected evidence artifact, mirroring the 17 CSV columns.

    `present_but_unparsed_dates` records which date fields had a non-empty value
    that failed to parse, so the integrity auditor can tell "blank" apart from
    "malformed" without re-reading the raw CSV.
    """

    evidence_id: str
    requirement_id: str
    requirement_description: str
    framework: str
    evidence_type: str
    collected_by: str
    collector_email: str
    collection_date: date | None = None
    freshness_days: int | None = None
    evidence_summary: str
    reviewed_by: str | None = None
    reviewer_email: str | None = None
    review_date: date | None = None
    evidence_location: str | None = None
    confidence_score: float | None = None
    status: str
    anomaly_marker: str | None = None
    present_but_unparsed_dates: list[str] = []

    @field_validator("anomaly_marker", mode="before")
    @classmethod
    def _blank_marker_is_none(cls, v: Any) -> Any:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "EvidenceRecord":
        """Build a record from a raw string row, coercing types leniently."""
        unparsed: list[str] = []
        collection_date = _parse_date(row.get("collection_date"))
        review_date = _parse_date(row.get("review_date"))
        for field_name, parsed in (
            ("collection_date", collection_date),
            ("review_date", review_date),
        ):
            raw = str(row.get(field_name, "") or "").strip()
            if raw and parsed is None:
                unparsed.append(field_name)
        return cls(
            evidence_id=str(row.get("evidence_id", "") or "").strip(),
            requirement_id=str(row.get("requirement_id", "") or "").strip(),
            requirement_description=str(row.get("requirement_description", "") or ""),
            framework=str(row.get("framework", "") or "").strip(),
            evidence_type=str(row.get("evidence_type", "") or "").strip(),
            collected_by=str(row.get("collected_by", "") or "").strip(),
            collector_email=str(row.get("collector_email", "") or "").strip(),
            collection_date=collection_date,
            freshness_days=_parse_int(row.get("freshness_days")),
            evidence_summary=str(row.get("evidence_summary", "") or ""),
            reviewed_by=_clean_str(row.get("reviewed_by")),
            reviewer_email=_clean_str(row.get("reviewer_email")),
            review_date=review_date,
            evidence_location=_clean_str(row.get("evidence_location")),
            confidence_score=_parse_float(row.get("confidence_score")),
            status=str(row.get("status", "") or "").strip(),
            anomaly_marker=row.get("anomaly_marker"),
            present_but_unparsed_dates=unparsed,
        )


def load_evidence(path: str | Path) -> list[EvidenceRecord]:
    """Load evidence_artifacts.csv into typed records.

    Reads every column as a string with NA detection disabled, so the loader
    sees exactly what is in the file (blank stays blank, no surprise NaN), then
    coerces per-field. Malformed values do not raise; they surface as None and
    feed the integrity checks.
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    missing = [c for c in EVIDENCE_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"evidence CSV missing expected columns: {missing}")
    return [EvidenceRecord.from_row(row) for row in frame.to_dict(orient="records")]


class IntegrityFinding(BaseModel):
    """A single data-quality finding from the corpus auditor."""

    check_name: str
    severity: str
    affected_ids: list[str] = []
    affected_count: int = 0
    description: str

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {v!r}")
        return v


class Prediction(BaseModel):
    """One detector's call on a single evidence record.

    Every prediction is explainable: the anomaly class, a human-readable reason
    for why the rule fired, and the detector's self-assessed confidence (0..1).
    """

    anomaly_class: str
    reason: str
    confidence: float


class EvidenceLink(BaseModel):
    """A link from one evidence record to a requirement (or UNMAPPED).

    `method` records which mapping layer produced the link (exact_id,
    framework_rule, tfidf, or unmapped) so a report can show how each link was
    made. When `mapped` is False the record reached the similarity floor without
    a confident match; that is a reportable outcome, not an error.
    """

    evidence_id: str
    requirement_id: str | None
    method: str
    confidence: float
    mapped: bool


class RequirementScore(BaseModel):
    """Compliance status for one requirement, with evidence and a plain reason."""

    requirement_id: str
    status: str  # COMPLIANT | PARTIAL | GAP | UNKNOWN
    confidence: float
    evidence_ids: list[str] = []
    rationale: str = ""


class ComplianceSummary(BaseModel):
    """Roll-up across all requirements for one bench."""

    omniscience_index: float
    automation_rate: float
    total_requirements: int
    total_evidence: int
    unmapped_count: int
    status_breakdown: dict[str, int] = {}
    method_breakdown: dict[str, int] = {}


class EvalResult(BaseModel):
    """Metrics for one detector run, binary plus per-class."""

    mode: str
    detector: str
    label_source: str
    total: int
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    f1: float
    per_class: dict[str, dict[str, float]] = {}
    confusion: dict[str, dict[str, int]] = {}
