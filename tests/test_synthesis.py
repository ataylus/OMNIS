"""Tests for the synthetic generator and the detection regression bars."""

from pathlib import Path

import pytest

from omnis.detect import RuleBasedDetector
from omnis.evaluation import BaselineDetector, evaluate, load_label_overrides
from omnis.ingest import parse_policies
from omnis.models import EVIDENCE_COLUMNS, load_evidence
from omnis.synthesis import DEFAULT_SEED, generate_synthetic

SAMPLE = Path("data/sample/evidence_artifacts.csv")
POLICIES = Path("data/sample/policy_documents.txt")
SYNTHETIC_POLICIES = Path("data/synthetic/policy_documents.txt")


# --- synthetic policy scope ---

def test_synthetic_policy_file_has_six_policies_and_fifteen_requirements():
    """The synthetic side restores the advertised 6-framework enterprise scope.

    Three provided policies (verbatim) plus SOX, HIPAA, PCI-DSS, parsed by the
    same structural parser, so the report and dashboard show 12-15 requirements.
    """
    reqs = parse_policies(SYNTHETIC_POLICIES)
    assert len(reqs) == 15
    policies = {r.policy_id for r in reqs}
    assert policies == {
        "POL-ENC-001", "POL-AC-001", "POL-AUD-001",
        "POL-SOX-001", "POL-HIPAA-001", "POL-PCI-001",
    }
    # The 3 provided policies are carried verbatim, so their 9 ids survive.
    for rid in ("POL-ENC-001-R1", "POL-AC-001-R2", "POL-AUD-001-R3"):
        assert rid in {r.id for r in reqs}


def test_generator_references_the_full_synthetic_requirement_set():
    """Mappable rows reference the 15 synthetic requirement ids, not just 9."""
    syn_ids = {r.id for r in parse_policies(SYNTHETIC_POLICIES)}
    bench = generate_synthetic(500, seed=DEFAULT_SEED)
    assert bench.valid_requirement_ids == syn_ids
    mappable = {
        r.requirement_id for r in bench.records
        if r.requirement_id in bench.valid_requirement_ids
    }
    # Rows land on the added policies too, not only the original three.
    assert any(rid.startswith("POL-SOX-001") for rid in mappable)
    assert any(rid.startswith("POL-HIPAA-001") for rid in mappable)
    assert any(rid.startswith("POL-PCI-001") for rid in mappable)


# --- generator properties ---

def test_generator_is_deterministic():
    a = generate_synthetic(200, seed=123)
    b = generate_synthetic(200, seed=123)
    assert [r.model_dump() for r in a.records] == [r.model_dump() for r in b.records]


def test_generator_size_is_configurable():
    assert len(generate_synthetic(137, seed=1).records) == 137


def test_generator_covers_all_five_classes_and_clean():
    bench = generate_synthetic(500, seed=DEFAULT_SEED)
    markers = {r.anomaly_marker for r in bench.records}
    for cls in (
        "STALE_EVIDENCE", "COMPLIANCE_GAP", "UNREVIEWED_EVIDENCE",
        "MISSING_DOCUMENTATION", "INCOMPLETE_MAPPING",
    ):
        assert cls in markers
    assert None in markers  # clean rows present


def test_generator_injects_noise_near_target_rate():
    bench = generate_synthetic(500, seed=DEFAULT_SEED)
    rate = bench.noise_count / len(bench.records)
    assert 0.02 <= rate <= 0.08  # ~5% target with sampling slack


def test_generator_includes_orphan_mappings():
    bench = generate_synthetic(500, seed=DEFAULT_SEED)
    orphans = [r for r in bench.records if r.requirement_id not in bench.valid_requirement_ids]
    assert orphans  # INCOMPLETE_MAPPING scenario produces unmappable refs


def test_generated_records_match_csv_schema():
    bench = generate_synthetic(10, seed=1)
    # EvidenceRecord carries every CSV column (plus the derived helper field).
    fields = set(bench.records[0].model_dump().keys())
    for col in EVIDENCE_COLUMNS:
        assert col in fields


# --- regression bars ---

def test_rules_meets_bar_on_synthetic_bench():
    """The rule detector must clear the stated bar, and not be a tautology."""
    bench = generate_synthetic(500, seed=DEFAULT_SEED)
    result = evaluate(bench.records, RuleBasedDetector(bench.valid_requirement_ids))
    assert result.precision > 0.70
    assert result.recall > 0.60
    # Upper bound proves the bench is not tautological (noise/boundaries bite).
    assert result.precision < 0.99


def test_provided_sample_floor_does_not_silently_degrade():
    """Floor-assert current measured numbers on the provided sample.

    The sample's in-band markers are independent of features, so these numbers
    are diagnostic, not a quality target. We pin them so a later change that
    alters detection on the sample is noticed.
    """
    records = load_evidence(SAMPLE)
    known = {r.id for r in parse_policies(POLICIES)}

    baseline = evaluate(records, BaselineDetector())
    assert baseline.tp == 66 and baseline.fp == 177 and baseline.fn == 65
    assert baseline.precision == pytest.approx(0.272, abs=0.005)
    assert baseline.recall == pytest.approx(0.504, abs=0.005)

    # All 500 sample rows reference orphan requirement_ids, so the rule detector
    # flags every row as INCOMPLETE_MAPPING: recall 1.0, precision == base rate.
    rules = evaluate(records, RuleBasedDetector(known))
    assert rules.recall == pytest.approx(1.0)
    assert rules.precision == pytest.approx(131 / 500)
