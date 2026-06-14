"""Mock evidence collectors.

Two integrations (a CloudTrail-style log puller and a config-snapshot puller)
that read committed sample files and emit `EvidenceRecord` objects in the same
shape the rest of the pipeline consumes. They are clearly mocked: the file read
stands in for a live API call. See docs/COLLECTORS.md for the real-integration
notes. `collect_all()` runs every registered collector.
"""

from __future__ import annotations

from omnis.collectors import cloudtrail, config_snapshot
from omnis.models import EvidenceRecord

COLLECTORS = [cloudtrail, config_snapshot]


def collect_all() -> list[EvidenceRecord]:
    """Run every collector and return the combined evidence records."""
    records: list[EvidenceRecord] = []
    for collector in COLLECTORS:
        records.extend(collector.collect())
    return records


__all__ = ["collect_all", "cloudtrail", "config_snapshot", "COLLECTORS"]
