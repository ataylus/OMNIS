"""CloudTrail-style log puller (mock).

Reads a sample CloudTrail export and emits one Audit_Log evidence record per
event window. A live version replaces the file read with a CloudTrail
LookupEvents API call; everything downstream is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

from omnis.collectors.base import parse_timestamp
from omnis.models import EvidenceRecord

DEFAULT_SOURCE = Path("data/collectors/cloudtrail_events.json")
NAME = "cloudtrail"


def collect(source: str | Path = DEFAULT_SOURCE) -> list[EvidenceRecord]:
    """Pull audit-log evidence from the CloudTrail sample export."""
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    records: list[EvidenceRecord] = []
    for event in data["events"]:
        collected, age = parse_timestamp(event["eventTime"])
        completeness = float(event.get("completeness", 0.9))
        records.append(
            EvidenceRecord(
                evidence_id=f"CT-{event['eventId']}",
                requirement_id=event["requirement_id"],
                requirement_description=(
                    f"Audit-log evidence auto-collected for {event['requirement_id']}."
                ),
                framework="NIST",
                evidence_type="Audit_Log",
                collected_by="cloudtrail-collector (automated)",
                collector_email="collector@omnis.automation",
                collection_date=collected,
                freshness_days=age,
                evidence_summary=(
                    f"{event['eventName']} on {event['eventSource']}: "
                    f"{event['recordedEvents']} events captured"
                ),
                evidence_location=f"cloudtrail://{event['eventSource']}/{event['eventId']}",
                confidence_score=round(completeness, 2),
                status="Approved",
            )
        )
    return records
