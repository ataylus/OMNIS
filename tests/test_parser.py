"""Tests for the structural policy parser against the provided sample file."""

from pathlib import Path

import pytest

from omnis.ingest import parse_policies

SAMPLE = Path("data/sample/policy_documents.txt")


@pytest.fixture(scope="module")
def requirements():
    return parse_policies(SAMPLE)


def test_exactly_nine_requirements(requirements):
    assert len(requirements) == 9


def test_three_distinct_policies(requirements):
    policy_ids = {r.policy_id for r in requirements}
    assert policy_ids == {"POL-ENC-001", "POL-AC-001", "POL-AUD-001"}


def test_id_synthesis_format(requirements):
    ids = {r.id for r in requirements}
    assert "POL-ENC-001-R1" in ids
    assert "POL-AUD-001-R3" in ids
    # Three requirements per policy, all unique.
    assert len(ids) == 9


def test_field_extraction_enc_r1(requirements):
    r1 = next(r for r in requirements if r.id == "POL-ENC-001-R1")
    assert r1.number == 1
    assert r1.text == "All data at rest must be encrypted using AES-256 or stronger"
    assert r1.responsible == "Infrastructure Security"
    assert r1.scope == "Databases, file storage, backups"
    assert r1.evidence_source == "AWS KMS Configuration, Database Settings"
    assert r1.audit_frequency == "Monthly"
    assert r1.policy_title == "Data Encryption and Protection"
    assert r1.policy_version == "2.1"


def test_lowercase_scope_field_is_captured(requirements):
    # POL-ENC-001 REQUIREMENT 2 uses a lowercase "scope:" in the sample file.
    r2 = next(r for r in requirements if r.id == "POL-ENC-001-R2")
    assert r2.scope == "All encryption keys"


def test_compliance_mappings_parsed_as_list(requirements):
    r1 = next(r for r in requirements if r.id == "POL-ENC-001-R1")
    assert r1.compliance_mappings == [
        "GDPR Article 32",
        "NIST SC-7",
        "PCI-DSS 3.4",
    ]
    r2 = next(r for r in requirements if r.id == "POL-ENC-001-R2")
    assert r2.compliance_mappings == ["NIST SC-7", "ISO 27001 A.10.1.1"]
