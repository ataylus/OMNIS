"""Tests for the mock evidence collectors."""

from omnis.collectors import cloudtrail, collect_all, config_snapshot
from omnis.ingest import parse_policies
from omnis.mapping import map_evidence
from omnis.scoring import AUTO_TYPES

SYNTHETIC_POLICIES = "data/synthetic/policy_documents.txt"


def test_cloudtrail_collector_emits_audit_logs():
    records = cloudtrail.collect()
    assert records
    assert all(r.evidence_type == "Audit_Log" for r in records)
    assert all(r.evidence_id.startswith("CT-") for r in records)
    assert all(r.collection_date is not None and r.freshness_days is not None for r in records)


def test_config_collector_marks_noncompliant_as_needs_update():
    records = config_snapshot.collect()
    assert records
    assert all(r.evidence_type == "Configuration_Snapshot" for r in records)
    # the non-compliant snapshot in the sample is collected as Needs_Update
    assert any(r.status == "Needs_Update" for r in records)
    assert any(r.status == "Approved" for r in records)


def test_collected_evidence_is_automated_and_maps_to_requirements():
    records = collect_all()
    assert len(records) >= 8
    # every collected record is a machine-collectable (automated) type
    assert all(r.evidence_type in AUTO_TYPES for r in records)
    # and it flows through the existing linker against the synthetic requirements
    requirements = parse_policies(SYNTHETIC_POLICIES)
    links = map_evidence(records, requirements)
    mapped = [link for link in links if link.mapped]
    assert len(mapped) == len(records)  # all reference real requirement ids -> exact-id
    assert all(link.method == "exact_id" for link in mapped)
