"""Transparent rule-based anomaly detector for the 5 ground-truth classes.

Each rule encodes one compliance class definition taken from the problem
statement, in a fixed priority order (first match wins). The ordering is part of
the design: a record that is both old-and-rejected is reported STALE_EVIDENCE,
because age is the more actionable signal. Every prediction returns the class, a
plain-language reason, and a self-assessed confidence, so a report or auditor can
see exactly why a record was flagged.

A note on ground truth: the in-band anomaly_marker values in the provided sample
appear statistically independent of the record features (verified by
scripts/label_signal_analysis.py). These rules encode the product's intended
compliance logic regardless. They are validated against the synthetic bench,
where labels are generated from feature logic by construction, and we support the
advertised evidence_labels.csv via `eval --labels` if and when it is released.
"""

from __future__ import annotations

from collections.abc import Iterable

from omnis.freshness import DEFAULT_WINDOW_DAYS, REFERENCE_DATE, is_stale, record_age_days
from omnis.models import EvidenceRecord, Prediction

# Confidence threshold below which approved/accepted evidence is treated as
# having incomplete supporting documentation.
LOW_CONFIDENCE_THRESHOLD = 0.6


class RuleBasedDetector:
    """Predict an anomaly class for an evidence record, or None if clean.

    Parameters
    ----------
    known_requirement_ids:
        The set of requirement ids that resolve to a real policy requirement.
        Used by the INCOMPLETE_MAPPING rule to flag unmappable evidence. When
        empty, that rule is inert (we do not flag mapping gaps we cannot judge).
    """

    name = "rules"

    def __init__(
        self,
        known_requirement_ids: Iterable[str] | None = None,
        reference_date=REFERENCE_DATE,
    ) -> None:
        self.known_requirement_ids = set(known_requirement_ids or [])
        self.reference_date = reference_date

    def predict(self, record: EvidenceRecord) -> Prediction | None:
        age = record_age_days(record, self.reference_date)
        status = record.status
        confidence = record.confidence_score

        stale = self._stale(record, age, status)
        if stale is not None:
            return stale
        gap = self._compliance_gap(status)
        if gap is not None:
            return gap
        unreviewed = self._unreviewed(status)
        if unreviewed is not None:
            return unreviewed
        missing = self._missing_documentation(confidence)
        if missing is not None:
            return missing
        return self._incomplete_mapping(record)

    # --- one method per rule, each citing the class definition it encodes ---

    def _stale(self, record: EvidenceRecord, age: int | None, status: str) -> Prediction | None:
        """STALE_EVIDENCE: older than 90 days without approval.

        PS definition: "stale = evidence older than 90 days without approval".
        Age comes from the authoritative freshness_days field. Approved evidence
        is exempt (a recent approval re-establishes trust), which is why an
        old-but-approved record is correctly NOT flagged stale.
        """
        if age is None or status == "Approved":
            return None
        if not is_stale(age, window_days=DEFAULT_WINDOW_DAYS):
            return None
        overage = age - DEFAULT_WINDOW_DAYS
        confidence = min(0.99, 0.7 + overage / 300)
        return Prediction(
            anomaly_class="STALE_EVIDENCE",
            reason=(
                f"evidence is {age} days old (> {DEFAULT_WINDOW_DAYS}-day window) "
                f"and not Approved (status={status})"
            ),
            confidence=round(confidence, 3),
        )

    def _compliance_gap(self, status: str) -> Prediction | None:
        """COMPLIANCE_GAP: evidence reviewed and rejected.

        PS definition: "rejected = reviewed and rejected". A rejection means the
        control is not demonstrably met by this evidence, i.e. a compliance gap.
        """
        if status != "Rejected":
            return None
        return Prediction(
            anomaly_class="COMPLIANCE_GAP",
            reason="evidence was reviewed and Rejected; the control is not demonstrably met",
            confidence=0.85,
        )

    def _unreviewed(self, status: str) -> Prediction | None:
        """UNREVIEWED_EVIDENCE: collected but never adjudicated.

        Evidence sitting in Pending_Review has no reviewer sign-off, so it cannot
        yet support an audit claim.
        """
        if status != "Pending_Review":
            return None
        return Prediction(
            anomaly_class="UNREVIEWED_EVIDENCE",
            reason="status is Pending_Review; evidence has no reviewer sign-off",
            confidence=0.8,
        )

    def _missing_documentation(self, confidence: float | None) -> Prediction | None:
        """MISSING_DOCUMENTATION: incomplete evidence, expressed as low confidence.

        PS definitions: "low confidence = approved but below threshold" and
        "missing documentation = incomplete evidence". A confidence below 0.6 on
        evidence that was otherwise accepted signals the supporting documentation
        is incomplete.
        """
        if confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD:
            return None
        return Prediction(
            anomaly_class="MISSING_DOCUMENTATION",
            reason=(
                f"confidence_score {confidence} < {LOW_CONFIDENCE_THRESHOLD}; "
                f"supporting documentation appears incomplete"
            ),
            confidence=round(min(0.95, 0.6 + (LOW_CONFIDENCE_THRESHOLD - confidence)), 3),
        )

    def _incomplete_mapping(self, record: EvidenceRecord) -> Prediction | None:
        """INCOMPLETE_MAPPING: evidence that cannot be tied to a known requirement.

        Per the project design, unmappable evidence is itself a finding. When the
        requirement_id matches no parsed policy requirement, the evidence proves
        nothing auditable until the mapping is fixed.
        """
        if not self.known_requirement_ids:
            return None
        if record.requirement_id in self.known_requirement_ids:
            return None
        return Prediction(
            anomaly_class="INCOMPLETE_MAPPING",
            reason=(
                f"requirement_id {record.requirement_id!r} matches no known policy "
                f"requirement; evidence cannot be mapped"
            ),
            confidence=0.9,
        )
