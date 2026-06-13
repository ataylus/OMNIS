"""Seeded synthetic evidence generator with ground-truth labels by construction.

WHY THIS EXISTS: the in-band anomaly_marker labels in the provided sample appear
statistically independent of the record features (see
scripts/label_signal_analysis.py), so they cannot validate a feature-based
detector. This module builds a coherent corpus where each record's label is
derived from the same compliance rule logic the detector encodes, so detection
can be measured on a bench with a known signal.

HONESTY ABOUT WHAT THIS PROVES: because the labels come from the detector's own
rule logic, a perfect detector would score 100% here, which would be a
tautology. To keep the bench informative we inject realism:
  - ~5% label noise (a row's marker is corrupted while its features are not),
  - boundary cases straddling every rule threshold (age near 90, confidence near
    0.6), labeled by the strict rule so the detector's threshold handling is
    exercised honestly,
  - exception rows (old-but-approved evidence that is correctly NOT stale),
  - clean compliant rows.
The bench therefore validates the detector's IMPLEMENTATION and threshold
handling. It does not prove the rules are correct in the real world; only labeled
real data (the advertised evidence_labels.csv) can do that. Every generation rule
and the injected noise are documented in data/synthetic/DATA_CARD.md.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from omnis.detect.rules import LOW_CONFIDENCE_THRESHOLD, RuleBasedDetector
from omnis.freshness import DEFAULT_WINDOW_DAYS, REFERENCE_DATE
from omnis.ingest import parse_policies
from omnis.models import EVIDENCE_COLUMNS, EvidenceRecord, load_evidence

DEFAULT_N = 500
DEFAULT_SEED = 20260614
NOISE_RATE = 0.05

# The synthetic bench references the SAME 9 requirement ids parsed from the real
# policy file, so mapping and scoring tell one coherent story across both benches
# (exact-id mapping works on the synthetic bench; INCOMPLETE_MAPPING rows use
# ORPHAN-* ids that match no requirement, as before).
DEFAULT_POLICY_PATH = "data/sample/policy_documents.txt"

FRAMEWORKS = ["GDPR", "SOX", "NIST", "PCI-DSS", "ISO27001", "HIPAA"]
EVIDENCE_TYPES = [
    "Configuration_Snapshot", "Audit_Log", "Access_Report", "Encryption_Cert",
    "Training_Record", "Test_Result", "Policy_Document", "Screenshot",
]
SOURCE_SYSTEMS = ["AWS", "Azure", "Okta", "Splunk", "Vault", "GitHub", "CrowdStrike"]
FIRST_NAMES = ["Aisha", "Rohan", "Priya", "Michael", "Diya", "Thomas", "Neha", "Arjun"]
LAST_NAMES = ["Smith", "Patel", "Sharma", "Gupta", "Singh", "Lee", "Martin", "Nair"]

# Scenario mix. Roughly half the corpus is anomalous, spread across the 5 classes,
# plus a clean majority that includes the old-but-approved exception.
SCENARIO_WEIGHTS = {
    "clean": 0.45,
    "clean_old_approved": 0.05,
    "stale": 0.10,
    "gap": 0.10,
    "unreviewed": 0.10,
    "missing_doc": 0.10,
    "incomplete_mapping": 0.10,
}

# Probability a row is generated as a boundary case (deciding feature pushed next
# to its threshold). Boundaries are labeled by the strict rule, not as noise.
BOUNDARY_RATE = 0.15


@dataclass
class SyntheticBench:
    records: list[EvidenceRecord]
    valid_requirement_ids: set[str]
    noise_count: int = 0
    scenario_counts: dict[str, int] = field(default_factory=dict)


def _valid_ids(policy_path: str = DEFAULT_POLICY_PATH) -> list[str]:
    return [req.id for req in parse_policies(policy_path)]


def _oracle_label(row: dict, valid_ids: set[str]) -> str | None:
    """Label a row by the same rule logic the detector encodes (pre-noise)."""
    detector = RuleBasedDetector(valid_ids)
    record = EvidenceRecord.from_row(row)
    prediction = detector.predict(record)
    return prediction.anomaly_class if prediction is not None else None


def _build_features(scenario: str, rng: random.Random, valid_ids: list[str]) -> dict:
    """Generate the feature values for a scenario (before oracle labeling)."""
    boundary = rng.random() < BOUNDARY_RATE
    requirement_id = rng.choice(valid_ids)
    status = "Approved"
    confidence = round(rng.uniform(0.6, 1.0), 2)

    if scenario == "clean":
        age = rng.randint(0, DEFAULT_WINDOW_DAYS - 1)
    elif scenario == "clean_old_approved":
        age = rng.randint(DEFAULT_WINDOW_DAYS + 5, 180)  # old, but Approved -> not stale
    elif scenario == "stale":
        status = "Needs_Update"
        age = (
            rng.randint(DEFAULT_WINDOW_DAYS - 2, DEFAULT_WINDOW_DAYS + 3)
            if boundary
            else rng.randint(DEFAULT_WINDOW_DAYS + 5, 180)
        )
    elif scenario == "gap":
        status = "Rejected"
        age = rng.randint(0, DEFAULT_WINDOW_DAYS - 1)
        confidence = round(rng.uniform(0.5, 1.0), 2)
    elif scenario == "unreviewed":
        status = "Pending_Review"
        age = rng.randint(0, DEFAULT_WINDOW_DAYS - 1)
    elif scenario == "missing_doc":
        status = rng.choice(["Approved", "Needs_Update"])
        age = rng.randint(0, DEFAULT_WINDOW_DAYS - 1)
        confidence = (
            round(rng.uniform(0.56, 0.63), 2)
            if boundary
            else round(rng.uniform(0.4, 0.59), 2)
        )
    elif scenario == "incomplete_mapping":
        status = "Approved"
        age = rng.randint(0, DEFAULT_WINDOW_DAYS - 1)
        requirement_id = f"ORPHAN-REQ-{rng.randint(1000, 9999)}"
    else:  # pragma: no cover - guarded by the scenario list
        raise ValueError(scenario)

    collection_date = REFERENCE_DATE - timedelta(days=age)
    review_date = collection_date + timedelta(days=rng.randint(1, 20))
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    rfirst, rlast = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    return {
        "evidence_id": "",  # filled by caller
        "requirement_id": requirement_id,
        "requirement_description": "Synthetic control requirement",
        "framework": rng.choice(FRAMEWORKS),
        "evidence_type": rng.choice(EVIDENCE_TYPES),
        "collected_by": f"{first} {last}",
        "collector_email": f"{first.lower()}.{last.lower()}@company.com",
        "collection_date": collection_date.isoformat(),
        "freshness_days": str(age),
        "evidence_summary": f"{rng.choice(SOURCE_SYSTEMS)} record with {rng.randint(50, 9000)} entries",
        "reviewed_by": f"{rfirst} {rlast}",
        "reviewer_email": f"{rfirst.lower()}.{rlast.lower()}@company.com",
        "review_date": review_date.isoformat(),
        "evidence_location": f"Vault-{rng.randint(1, 9)}/Path-{rng.randint(1, 99)}",
        "confidence_score": str(confidence),
        "status": status,
        "anomaly_marker": "",  # filled after oracle labeling + noise
    }


def _scenarios(rng: random.Random, n: int) -> list[str]:
    names = list(SCENARIO_WEIGHTS)
    weights = [SCENARIO_WEIGHTS[k] for k in names]
    return rng.choices(names, weights=weights, k=n)


def generate_synthetic(
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    valid_requirement_ids: list[str] | None = None,
) -> SyntheticBench:
    """Generate a deterministic synthetic bench of `n` records.

    Mappable rows reference `valid_requirement_ids` (defaults to the 9 ids parsed
    from the real policy file); INCOMPLETE_MAPPING rows reference ORPHAN-* ids.
    """
    rng = random.Random(seed)
    valid_ids = list(valid_requirement_ids) if valid_requirement_ids else _valid_ids()
    valid_set = set(valid_ids)
    scenario_counts: dict[str, int] = {}
    noise_count = 0
    records: list[EvidenceRecord] = []
    other_classes = [
        "STALE_EVIDENCE", "COMPLIANCE_GAP", "UNREVIEWED_EVIDENCE",
        "MISSING_DOCUMENTATION", "INCOMPLETE_MAPPING",
    ]

    for i, scenario in enumerate(_scenarios(rng, n)):
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
        row = _build_features(scenario, rng, valid_ids)
        row["evidence_id"] = f"SYN{i:05d}"
        label = _oracle_label(row, valid_set)  # None == clean

        # Inject ~5% label noise: corrupt the marker without touching features,
        # so the detector (which reads features) is provably wrong on these rows.
        if rng.random() < NOISE_RATE:
            noise_count += 1
            if label is None:
                # clean -> labeled anomalous (a false negative for the detector)
                label = rng.choice(other_classes)
            else:
                # anomalous -> labeled clean (a false positive for the detector)
                label = None

        row["anomaly_marker"] = label or ""
        records.append(EvidenceRecord.from_row(row))

    return SyntheticBench(
        records=records,
        valid_requirement_ids=valid_set,
        noise_count=noise_count,
        scenario_counts=scenario_counts,
    )


def _rows_for_csv(records: list[EvidenceRecord]) -> list[dict]:
    rows = []
    for r in records:
        rows.append(
            {
                "evidence_id": r.evidence_id,
                "requirement_id": r.requirement_id,
                "requirement_description": r.requirement_description,
                "framework": r.framework,
                "evidence_type": r.evidence_type,
                "collected_by": r.collected_by,
                "collector_email": r.collector_email,
                "collection_date": r.collection_date.isoformat() if r.collection_date else "",
                "freshness_days": "" if r.freshness_days is None else str(r.freshness_days),
                "evidence_summary": r.evidence_summary,
                "reviewed_by": r.reviewed_by or "",
                "reviewer_email": r.reviewer_email or "",
                "review_date": r.review_date.isoformat() if r.review_date else "",
                "evidence_location": r.evidence_location or "",
                "confidence_score": "" if r.confidence_score is None else str(r.confidence_score),
                "status": r.status,
                "anomaly_marker": r.anomaly_marker or "",
            }
        )
    return rows


def materialize(out_dir: str | Path, n: int = DEFAULT_N, seed: int = DEFAULT_SEED) -> SyntheticBench:
    """Write the synthetic CSV, the valid-id list, and a DATA_CARD to out_dir."""
    bench = generate_synthetic(n, seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "evidence_artifacts.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EVIDENCE_COLUMNS))
        writer.writeheader()
        writer.writerows(_rows_for_csv(bench.records))

    ids_path = out / "valid_requirement_ids.txt"
    ids_path.write_text(
        "\n".join(sorted(bench.valid_requirement_ids)) + "\n", encoding="utf-8"
    )

    _write_data_card(out / "DATA_CARD.md", bench, n, seed)
    return bench


def load_valid_requirement_ids(path: str | Path) -> set[str]:
    text = Path(path).read_text(encoding="utf-8")
    return {line.strip() for line in text.splitlines() if line.strip()}


def _write_data_card(path: Path, bench: SyntheticBench, n: int, seed: int) -> None:
    pos = sum(1 for r in bench.records if r.anomaly_marker)
    from collections import Counter

    class_counts = Counter(r.anomaly_marker for r in bench.records if r.anomaly_marker)
    scenario_lines = "\n".join(
        f"| {k} | {v} |" for k, v in sorted(bench.scenario_counts.items())
    )
    class_lines = "\n".join(f"| {k} | {v} |" for k, v in sorted(class_counts.items()))
    card = f"""# Synthetic evidence bench: data card

Generated by `omnis.synthesis.generator`. Seed `{seed}`, `{n}` rows, schema
identical to `data/sample/evidence_artifacts.csv` (17 columns).

Regenerate with:

    python -m omnis synth --out data/synthetic --seed {seed} --n {n}

## Why this bench exists

The in-band `anomaly_marker` values in the provided sample appear statistically
independent of the record features (reproduce with
`python scripts/label_signal_analysis.py`). We read that as a sign the markers
are not the intended detection target; we believe the advertised
`evidence_labels.csv` holds the intended ground truth and support it via
`omnis eval --labels`. To validate the detector in the meantime, this bench
assigns each record a label derived from the same compliance rule logic the
detector encodes.

## What it is honestly worth

Labels here come from the detector's own rule logic, so a perfect detector would
score ~100%, which would be a tautology. To keep the bench informative we inject
realism (below). The bench validates the detector's IMPLEMENTATION and threshold
handling. It does not prove the rules are correct in the real world.

## Generation rules (per scenario)

Age uses the authoritative `freshness_days` field. Window = {DEFAULT_WINDOW_DAYS} days,
low-confidence threshold = {LOW_CONFIDENCE_THRESHOLD}. Mappable rows reference the 9
requirement ids parsed from the real policy file (so mapping/scoring work across
both benches); INCOMPLETE_MAPPING rows reference ORPHAN-* ids.

- clean: Approved, age < {DEFAULT_WINDOW_DAYS}, confidence >= {LOW_CONFIDENCE_THRESHOLD}, mappable -> no anomaly.
- clean_old_approved (exception): Approved, age > {DEFAULT_WINDOW_DAYS} -> NOT stale (recent approval exempts).
- stale -> STALE_EVIDENCE: not Approved, age > {DEFAULT_WINDOW_DAYS}.
- gap -> COMPLIANCE_GAP: status Rejected, age < {DEFAULT_WINDOW_DAYS}.
- unreviewed -> UNREVIEWED_EVIDENCE: status Pending_Review.
- missing_doc -> MISSING_DOCUMENTATION: confidence < {LOW_CONFIDENCE_THRESHOLD}.
- incomplete_mapping -> INCOMPLETE_MAPPING: requirement_id not in the valid set.

Each label is assigned by running the detector's rule priority on the generated
features (the "oracle"), so boundary rows are labeled by the strict rule.

## Injected realism

- Label noise: {NOISE_RATE:.0%} of rows have their marker corrupted while features
  are left intact ({bench.noise_count} rows in this build). Clean rows become a
  random anomaly class (false negatives for the detector); anomalous rows become
  blank (false positives). This caps achievable precision/recall below 1.0.
- Boundary cases: {BOUNDARY_RATE:.0%} of rows place the deciding feature next to its
  threshold (age near {DEFAULT_WINDOW_DAYS}, confidence near {LOW_CONFIDENCE_THRESHOLD}).
- Exception rows: old-but-approved evidence that is correctly not stale.

## Composition (this build)

Rows: {n}. Anomalous: {pos}. Clean: {n - pos}. Injected noise rows: {bench.noise_count}.

| scenario | count |
|---|---|
{scenario_lines}

| anomaly_marker (post-noise) | count |
|---|---|
{class_lines}
"""
    path.write_text(card, encoding="utf-8")


def load_synthetic_bench(
    csv_path: str | Path, ids_path: str | Path
) -> tuple[list[EvidenceRecord], set[str]]:
    """Load a materialized synthetic bench (records + valid requirement ids)."""
    records = load_evidence(csv_path)
    valid_ids = load_valid_requirement_ids(ids_path)
    return records, valid_ids
