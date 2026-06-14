"""Config snapshot puller (mock).

Reads a sample AWS Config-style snapshot and emits one Configuration_Snapshot
evidence record per resource. A live version replaces the file read with an AWS
Config / cloud config API call; everything downstream is unchanged. A
non-compliant snapshot is collected as Needs_Update with lower confidence, so the
scorer and integrity auditor can act on it.
"""

from __future__ import annotations

import json
from pathlib import Path

from omnis.collectors.base import parse_timestamp
from omnis.models import EvidenceRecord

DEFAULT_SOURCE = Path("data/collectors/config_snapshots.json")
NAME = "config_snapshot"


def collect(source: str | Path = DEFAULT_SOURCE) -> list[EvidenceRecord]:
    """Pull configuration-snapshot evidence from the Config sample."""
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    records: list[EvidenceRecord] = []
    for snap in data["snapshots"]:
        collected, age = parse_timestamp(snap["capturedAt"])
        compliant = bool(snap.get("compliant", True))
        records.append(
            EvidenceRecord(
                evidence_id=f"CFG-{snap['snapshotId']}",
                requirement_id=snap["requirement_id"],
                requirement_description=(
                    f"Configuration snapshot auto-collected for {snap['requirement_id']}."
                ),
                framework="CIS",
                evidence_type="Configuration_Snapshot",
                collected_by="config-collector (automated)",
                collector_email="collector@omnis.automation",
                collection_date=collected,
                freshness_days=age,
                evidence_summary=(
                    f"{snap['resourceType']} {snap['resourceId']}: {snap['setting']}"
                ),
                evidence_location=f"awsconfig://{snap['resourceType']}/{snap['resourceId']}",
                confidence_score=0.95 if compliant else 0.5,
                status="Approved" if compliant else "Needs_Update",
            )
        )
    return records
