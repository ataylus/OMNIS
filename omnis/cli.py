"""Command line interface for OMNIS.

Everything runs headless and offline:
  python -m omnis run                 parse policies + audit the evidence corpus
  python -m omnis eval [opts]          score detectors on both benches
  python -m omnis synth [opts]         (re)generate the synthetic bench

`eval` scores the baseline and the rule detector on two benches side by side:
the provided sample (in-band markers, which appear independent of features) and
the synthetic bench (labels by construction, where the precision/recall bar
applies). Block 2 wires up freshness, detection, and synthesis.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from omnis.detect import RuleBasedDetector
from omnis.evaluation import (
    BaselineDetector,
    evaluate,
    format_result,
    load_label_overrides,
    save_result,
)
from omnis.evaluation.harness import Detector
from omnis.ingest import parse_policies
from omnis.integrity import audit_corpus
from omnis.models import EvalResult, load_evidence
from omnis.synthesis import load_synthetic_bench, materialize

DEFAULT_POLICIES = Path("data/sample/policy_documents.txt")
DEFAULT_EVIDENCE = Path("data/sample/evidence_artifacts.csv")
DEFAULT_EVAL_OUT = Path("reports/eval_latest.json")
SYNTHETIC_DIR = Path("data/synthetic")
SYNTHETIC_CSV = SYNTHETIC_DIR / "evidence_artifacts.csv"
SYNTHETIC_IDS = SYNTHETIC_DIR / "valid_requirement_ids.txt"

# The bar from the problem statement, applied to the synthetic bench.
BAR_PRECISION = 0.70
BAR_RECALL = 0.60


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


def _detectors(selection: str, known_ids: set[str]) -> dict[str, Detector]:
    available: dict[str, Detector] = {
        "baseline": BaselineDetector(),
        "rules": RuleBasedDetector(known_ids),
    }
    if selection == "both":
        return available
    return {selection: available[selection]}


def _bench_line(name: str, result: EvalResult) -> str:
    return (
        f"  {name:<10}{result.precision:>8.3f}{result.recall:>8.3f}{result.f1:>8.3f}"
        f"{result.tp:>6}{result.fp:>6}{result.fn:>6}{result.tn:>6}"
    )


def _bench_header() -> str:
    return (
        f"  {'detector':<10}{'prec':>8}{'rec':>8}{'f1':>8}"
        f"{'TP':>6}{'FP':>6}{'FN':>6}{'TN':>6}"
    )


def _cmd_eval(args: argparse.Namespace) -> int:
    payload: dict[str, dict] = {}
    rc = 0

    # Bench A: provided sample, in-band markers (or --labels override).
    sample_records = load_evidence(args.evidence)
    sample_known = {r.id for r in parse_policies(args.policies)}
    overrides = None
    sample_label_source = "anomaly_marker"
    if args.labels:
        overrides = load_label_overrides(args.labels)
        sample_label_source = str(args.labels)
    print("=== Provided sample ({}) ===".format(args.evidence))
    print("  NOTE: the in-band anomaly_marker appears statistically independent of")
    print("  record features (reproduce: python scripts/label_signal_analysis.py).")
    print("  We believe the advertised evidence_labels.csv holds the intended")
    print("  ground truth; supply it with --labels. Numbers below reflect the")
    print("  in-band markers as-is.")
    print(_bench_header())
    payload["provided_sample"] = {}
    for name, detector in _detectors(args.detector, sample_known).items():
        result = evaluate(sample_records, detector, overrides, sample_label_source)
        payload["provided_sample"][name] = result.model_dump()
        print(_bench_line(name, result))
    print()

    # Bench B: synthetic bench, labels by construction; the bar applies here.
    if SYNTHETIC_CSV.exists() and SYNTHETIC_IDS.exists():
        syn_records, syn_known = load_synthetic_bench(SYNTHETIC_CSV, SYNTHETIC_IDS)
        print("=== Synthetic bench ({}) ===".format(SYNTHETIC_CSV))
        print(
            f"  BAR: precision > {BAR_PRECISION:.2f} AND recall > {BAR_RECALL:.2f} "
            f"(labels by construction)"
        )
        print(_bench_header())
        payload["synthetic"] = {}
        rules_result = None
        for name, detector in _detectors(args.detector, syn_known).items():
            result = evaluate(syn_records, detector, None, "synthetic_construction")
            payload["synthetic"][name] = result.model_dump()
            print(_bench_line(name, result))
            if name == "rules":
                rules_result = result
        if rules_result is not None:
            passed = rules_result.precision > BAR_PRECISION and rules_result.recall > BAR_RECALL
            print()
            print(f"  rules vs bar: {'PASS' if passed else 'FAIL'}")
            print()
            print("Per-class detail (rules on synthetic bench):")
            print(format_result(rules_result))
            if not passed:
                rc = 1
    else:
        print("Synthetic bench not found. Generate it with: python -m omnis synth")
    print()

    save_result_payload(payload, args.out)
    print(f"Saved metrics to {args.out}")
    return rc


def save_result_payload(payload: dict, path: str | Path) -> None:
    import json

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _cmd_synth(args: argparse.Namespace) -> int:
    bench = materialize(args.out, n=args.n, seed=args.seed)
    pos = sum(1 for r in bench.records if r.anomaly_marker)
    print(f"Wrote synthetic bench to {args.out}/")
    print(f"  rows={len(bench.records)} anomalous={pos} clean={len(bench.records) - pos}")
    print(f"  injected noise rows={bench.noise_count} seed={args.seed}")
    print(f"  files: evidence_artifacts.csv, valid_requirement_ids.txt, DATA_CARD.md")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omnis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="parse policies and audit the evidence corpus")
    run_p.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    run_p.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    run_p.set_defaults(func=_cmd_run)

    eval_p = sub.add_parser("eval", help="score detectors on both benches")
    eval_p.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    eval_p.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    eval_p.add_argument(
        "--detector", choices=["baseline", "rules", "both"], default="both"
    )
    eval_p.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="external labels CSV (evidence_id,is_anomaly,anomaly_type) overriding sample markers",
    )
    eval_p.add_argument("--out", type=Path, default=DEFAULT_EVAL_OUT)
    eval_p.set_defaults(func=_cmd_eval)

    synth_p = sub.add_parser("synth", help="(re)generate the synthetic bench")
    synth_p.add_argument("--out", type=Path, default=SYNTHETIC_DIR)
    synth_p.add_argument("--n", type=int, default=500)
    synth_p.add_argument("--seed", type=int, default=20260614)
    synth_p.set_defaults(func=_cmd_synth)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
