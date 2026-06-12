"""Command line interface for OMNIS.

Everything runs headless and offline:
  python -m omnis run               parse policies + audit the evidence corpus
  python -m omnis eval [--labels P]  score the baseline detector, save metrics

Block 1 wires up ingest, integrity, and evaluation. Mapping, scoring, freshness,
and reporting arrive in later blocks.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from omnis.evaluation import (
    BaselineDetector,
    evaluate,
    format_result,
    load_label_overrides,
    save_result,
)
from omnis.ingest import parse_policies
from omnis.integrity import audit_corpus
from omnis.models import load_evidence

# Default data locations (the provided sample set is the primary eval set).
DEFAULT_POLICIES = Path("data/sample/policy_documents.txt")
DEFAULT_EVIDENCE = Path("data/sample/evidence_artifacts.csv")
DEFAULT_EVAL_OUT = Path("reports/eval_latest.json")


def _cmd_run(args: argparse.Namespace) -> int:
    requirements = parse_policies(args.policies)
    records = load_evidence(args.evidence)
    findings = audit_corpus(records, requirements)

    print(f"Parsed {len(requirements)} requirements from {args.policies}")
    policy_ids = sorted({r.policy_id for r in requirements})
    print(f"Policies: {', '.join(policy_ids)}")
    print(f"Loaded {len(records)} evidence records from {args.evidence}")
    print()
    print(f"Integrity findings: {len(findings)}")
    for f in findings:
        sample = f", sample: {', '.join(f.affected_ids)}" if f.affected_ids else ""
        print(f"  [{f.severity:<6}] {f.check_name} (count={f.affected_count}){sample}")
        print(f"           {f.description}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    records = load_evidence(args.evidence)
    overrides = None
    label_source = "anomaly_marker"
    if args.labels:
        overrides = load_label_overrides(args.labels)
        label_source = str(args.labels)
    result = evaluate(records, BaselineDetector(), overrides, label_source)
    save_result(result, args.out)
    print(format_result(result))
    print()
    print(f"Saved metrics to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omnis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="parse policies and audit the evidence corpus")
    run_p.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    run_p.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    run_p.set_defaults(func=_cmd_run)

    eval_p = sub.add_parser("eval", help="score the baseline detector vs ground truth")
    eval_p.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    eval_p.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="external labels CSV (evidence_id,is_anomaly,anomaly_type) overriding in-band markers",
    )
    eval_p.add_argument("--out", type=Path, default=DEFAULT_EVAL_OUT)
    eval_p.set_defaults(func=_cmd_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
