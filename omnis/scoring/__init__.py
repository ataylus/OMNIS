"""Per-requirement compliance scoring and headline roll-ups."""

from omnis.scoring.scorer import (
    AUTO_TYPES,
    MANUAL_TYPES,
    automation_rate,
    classify_evidence,
    mapped_records_by_requirement,
    omniscience_index,
    score_corpus,
    score_requirement,
)

__all__ = [
    "score_corpus",
    "score_requirement",
    "classify_evidence",
    "mapped_records_by_requirement",
    "omniscience_index",
    "automation_rate",
    "AUTO_TYPES",
    "MANUAL_TYPES",
]
