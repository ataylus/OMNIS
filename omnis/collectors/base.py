"""Shared helpers for the mock evidence collectors.

These collectors are mock integrations: they read a committed sample file rather
than calling a live API, but they produce the exact `EvidenceRecord` shape the
rest of the pipeline consumes, so collected records flow through map -> score ->
integrity unchanged. Their evidence types are machine-collectable (AUTO_TYPES in
scoring), so every collected row counts toward the Automation Rate. Swapping the
file read for a real API call is the only change a live collector needs; the
mapping for each source is documented in docs/COLLECTORS.md.
"""

from __future__ import annotations

from datetime import date, datetime

from omnis.freshness import REFERENCE_DATE


def parse_timestamp(iso_ts: str) -> tuple[date, int]:
    """Return (collection_date, age_in_days) for an ISO-8601 timestamp.

    Age is measured against the project's fixed REFERENCE_DATE so collected
    records age on the same clock as the rest of the corpus and runs reproduce.
    """
    parsed = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).date()
    return parsed, max((REFERENCE_DATE - parsed).days, 0)
