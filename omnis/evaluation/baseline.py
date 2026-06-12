"""Trivial baseline anomaly detector.

This exists so the evaluation harness has a measurable subject from day one.
The rule is intentionally simple: evidence older than 90 days (by the stored
freshness_days field) is called STALE_EVIDENCE, everything else is negative.
Real detectors land in omnis/detect/ in a later block; this is the floor we
measure improvements against.
"""

from __future__ import annotations

from omnis.models import EvidenceRecord

STALE_THRESHOLD_DAYS = 90


class BaselineDetector:
    """Predict STALE_EVIDENCE when freshness_days > 90, else no anomaly."""

    name = "baseline_freshness>90"

    def predict(self, record: EvidenceRecord) -> str | None:
        if record.freshness_days is not None and record.freshness_days > STALE_THRESHOLD_DAYS:
            return "STALE_EVIDENCE"
        return None
