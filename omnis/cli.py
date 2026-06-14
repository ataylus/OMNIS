"""Command line interface for OMNIS.

Everything runs headless and offline:
  python -m omnis run                 parse policies + audit + one-line score summary
  python -m omnis eval [opts]          score detectors on both benches
  python -m omnis score [opts]         map evidence + score compliance, both benches
  python -m omnis report [opts]        write an auditor-ready JSON + PDF report
  python -m omnis serve [opts]         serve the single-page dashboard locally
  python -m omnis synth [opts]         (re)generate the synthetic bench

`eval` scores the baseline and the rule detector on two benches side by side.
`score` maps evidence to requirements and derives per-requirement compliance
status, the Omniscience Index, and the Automation Rate. Block 3 adds mapping and
scoring.
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
)
from omnis.evaluation.harness import Detector
from omnis.ingest import parse_policies
from omnis.integrity import audit_corpus
from omnis.dashboard import build_dashboard_data, serve, write_static
from omnis.mapping import content_link_accuracy, map_evidence
from omnis.models import EvalResult, Requirement, load_evidence
from omnis.report import build_report, write_report
from omnis.scoring import score_corpus
from omnis.synthesis import generate_synthetic, load_synthetic_bench, materialize

DEFAULT_POLICIES = Path("data/sample/policy_documents.txt")
DEFAULT_EVIDENCE = Path("data/sample/evidence_artifacts.csv")
DEFAULT_EVAL_OUT = Path("reports/eval_latest.json")
SYNTHETIC_DIR = Path("data/synthetic")
SYNTHETIC_CSV = SYNTHETIC_DIR / "evidence_artifacts.csv"
SYNTHETIC_IDS = SYNTHETIC_DIR / "valid_requirement_ids.txt"
# The synthetic bench is scored against its own 6-policy / 15-requirement set
# (the 3 provided policies plus SOX, HIPAA, PCI-DSS). The provided sample bench
# always uses the 3-policy / 9-requirement file at DEFAULT_POLICIES.
SYNTHETIC_POLICIES = SYNTHETIC_DIR / "policy_documents.txt"

# The bar from the problem statement, applied to the synthetic bench.
BAR_PRECISION = 0.70
BAR_RECALL = 0.60


def _format_status(breakdown: dict) -> str:
    order = ["COMPLIANT", "PARTIAL", "GAP", "UNKNOWN"]
    parts = [f"{breakdown[s]} {s}" for s in order if breakdown.get(s)]
    return " · ".join(parts) if parts else "none"


def _card(title: str, rows: list[tuple[str, str]], width: int = 60) -> None:
    """Print a compact bordered scorecard with the headline metrics."""
    inner = width - 4
    print("  ╭" + "─" * (width - 2) + "╮")
    print("  │ " + title.ljust(inner) + " │")
    print("  ├" + "─" * (width - 2) + "┤")
    for label, value in rows:
        print("  │ " + f"{label:<19}{value}".ljust(inner) + " │")
    print("  ╰" + "─" * (width - 2) + "╯")


def _cmd_run(args: argparse.Namespace) -> int:
    requirements = parse_policies(args.policies)
    records = load_evidence(args.evidence)
    findings = audit_corpus(records, requirements)
    links = map_evidence(records, requirements)
    scores, summary = score_corpus(requirements, records, links)

    print(f"Parsed {len(requirements)} requirements from {args.policies}")
    policy_ids = sorted({r.policy_id for r in requirements})
    print(f"Policies: {', '.join(policy_ids)}")
    print(f"Loaded {len(records)} evidence records from {args.evidence}")
    print()
    _card(
        "OMNIS  ·  compliance scorecard",
        [
            ("Omniscience Index", f"{summary.omniscience_index} / 100"),
            ("Automation Rate", f"{summary.automation_rate} %"),
            ("Status", _format_status(summary.status_breakdown)),
            ("Integrity findings", str(len(findings))),
        ],
    )
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

        # Evidence linking: a hard ablation. Hide the requirement_id and ask the
        # content layers (framework + TF-IDF) to recover the right requirement.
        syn_reqs = parse_policies(SYNTHETIC_POLICIES)
        link_acc = content_link_accuracy(syn_records, syn_reqs)
        payload["link_accuracy"] = link_acc
        print()
        print("Evidence linking (content recovery, exact id ablated):")
        print(
            f"  correct requirement: {link_acc['exact_hits']}/{link_acc['total']} "
            f"({link_acc['exact_accuracy'] * 100:.1f}%)"
        )
        print(
            f"  correct policy area: {link_acc['policy_hits']}/{link_acc['total']} "
            f"({link_acc['policy_accuracy'] * 100:.1f}%)"
        )
        print(
            f"  left unmapped: {link_acc['unmapped']}    "
            f"random baseline: {link_acc['random_baseline'] * 100:.1f}%"
        )
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


def _cmd_report(args: argparse.Namespace) -> int:
    if args.bench == "synthetic":
        if not (SYNTHETIC_CSV.exists() and SYNTHETIC_IDS.exists()):
            print("Synthetic bench not found. Generate it with: python -m omnis synth")
            return 1
        # The synthetic bench carries the full 6-policy / 15-requirement scope.
        requirements = parse_policies(SYNTHETIC_POLICIES)
        records, _ = load_synthetic_bench(SYNTHETIC_CSV, SYNTHETIC_IDS)
        bench_label = "synthetic"
    else:
        requirements = parse_policies(args.policies)
        records = load_evidence(args.evidence)
        bench_label = "provided sample"

    links = map_evidence(records, requirements)
    findings = audit_corpus(records, requirements)
    report = build_report(bench_label, requirements, records, links, findings)
    json_path, pdf_path = write_report(report, args.out)

    es = report["executive_summary"]
    print(f"Report for {bench_label} bench:")
    print(
        f"  Omniscience Index {es['omniscience_index']}/100, "
        f"Automation Rate {es['automation_rate']}%, "
        f"statuses {es['status_breakdown']}"
    )
    print(f"  Wrote {json_path}")
    print(f"  Wrote {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.write:
        data = build_dashboard_data(args.policies)
        html_path, json_path = write_static(data, args.write, initial_bench=args.bench)
        print(f"Wrote self-contained dashboard to {html_path}")
        print(f"Wrote static payload to {json_path}")
        print(f"Open {html_path} directly in a browser (no server needed).")
        return 0
    serve(port=args.port, initial_bench=args.bench, policies=args.policies)
    return 0


def _cmd_synth(args: argparse.Namespace) -> int:
    bench = materialize(args.out, n=args.n, seed=args.seed)
    pos = sum(1 for r in bench.records if r.anomaly_marker)
    print(f"Wrote synthetic bench to {args.out}/")
    print(f"  rows={len(bench.records)} anomalous={pos} clean={len(bench.records) - pos}")
    print(f"  injected noise rows={bench.noise_count} seed={args.seed}")
    print(f"  files: evidence_artifacts.csv, valid_requirement_ids.txt, DATA_CARD.md")
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """Run the mock collectors and show the auto-collected evidence flowing in."""
    from collections import Counter

    from omnis.collectors import COLLECTORS, collect_all
    from omnis.scoring import AUTO_TYPES

    records = collect_all()
    auto = sum(1 for r in records if r.evidence_type in AUTO_TYPES)
    auto_pct = round(100.0 * auto / len(records), 1) if records else 0.0
    _card(
        "OMNIS  ·  evidence collection",
        [
            ("Sources", f"{len(COLLECTORS)} (CloudTrail, AWS Config)"),
            ("Records collected", str(len(records))),
            ("Automated", f"{auto}/{len(records)}  ({auto_pct}%)"),
        ],
    )
    requirements = parse_policies(SYNTHETIC_POLICIES)
    links = map_evidence(records, requirements)
    mapped = sum(1 for link in links if link.mapped)
    methods = dict(Counter(link.method for link in links))
    print(f"  linked {mapped}/{len(records)} to requirements (methods {methods})")
    print()
    print(f"  {'evidence':<14}{'type':<24}{'status':<13}location")
    print("  " + "-" * 78)
    for r in records:
        print(f"  {r.evidence_id:<14}{r.evidence_type:<24}{r.status:<13}{r.evidence_location}")
    return 0


DEFAULT_SCORE_OUT = Path("reports/score_latest.json")


def _score_bench(
    title: str, source: str, requirements, records, links_summary_out: dict, key: str
) -> None:
    links = map_evidence(records, requirements)
    scores, summary = score_corpus(requirements, records, links)
    _card(
        f"OMNIS  ·  {title}",
        [
            ("Omniscience Index", f"{summary.omniscience_index} / 100"),
            ("Automation Rate", f"{summary.automation_rate} %"),
            ("Status", _format_status(summary.status_breakdown)),
        ],
    )
    print(f"  source: {source}")
    print(
        f"  evidence {summary.total_evidence}   unmapped {summary.unmapped_count}   "
        f"methods {summary.method_breakdown}"
    )
    print()
    print(f"  {'requirement':<16}{'status':<11}{'conf':>6}  {'evid':>5}  rationale")
    print("  " + "-" * 92)
    for s in scores:
        print(
            f"  {s.requirement_id:<16}{s.status:<11}{s.confidence:>6.3f}  "
            f"{len(s.evidence_ids):>5}  {s.rationale}"
        )
    print()
    links_summary_out[key] = {
        "summary": summary.model_dump(),
        "requirements": [s.model_dump() for s in scores],
    }


def _cmd_score(args: argparse.Namespace) -> int:
    requirements = parse_policies(args.policies)
    payload: dict = {}

    sample_records = load_evidence(args.evidence)
    _score_bench(
        "provided sample", str(args.evidence), requirements, sample_records, payload, "provided_sample"
    )

    if SYNTHETIC_CSV.exists() and SYNTHETIC_IDS.exists():
        syn_requirements = parse_policies(SYNTHETIC_POLICIES)
        syn_records, _ = load_synthetic_bench(SYNTHETIC_CSV, SYNTHETIC_IDS)
        _score_bench(
            "synthetic bench", str(SYNTHETIC_CSV), syn_requirements, syn_records, payload, "synthetic"
        )
    else:
        print("Synthetic bench not found. Generate it with: python -m omnis synth")
        print()

    save_result_payload(payload, args.out)
    print(f"Saved score payload to {args.out}")
    return 0


# Control topics used to synthesize realistic requirements for the perf test, so
# the TF-IDF index has genuine vocabulary diversity rather than identical text.
_PERF_TOPICS = [
    ("Encryption at Rest", "Sensitive data at rest must be encrypted with approved key management and rotation.", "Encryption_Cert", "NIST SC-28"),
    ("Access Logging", "All access to production systems must be logged centrally and reviewed.", "Audit_Log", "NIST AU-2"),
    ("Access Review", "Privileged access must be recertified and least privilege enforced.", "Access_Report", "NIST AC-2"),
    ("Configuration Baseline", "Systems must match an approved secure configuration baseline.", "Configuration_Snapshot", "CIS 5.1"),
    ("Vulnerability Testing", "Externally facing services must be scanned and findings remediated.", "Test_Result", "PCI-DSS 11.2"),
    ("Backup and Recovery", "Critical data must be backed up and restoration tested periodically.", "Configuration_Snapshot", "ISO27001 A.12.3"),
    ("Change Management", "Production changes must be approved, recorded, and reversible.", "Audit_Log", "SOX ITGC"),
    ("Data Retention", "Personal data must be retained only as long as lawfully required.", "Policy_Document", "GDPR Art.5"),
    ("Incident Response", "Security incidents must be detected, triaged, and reported on time.", "Audit_Log", "NIST IR-4"),
]
_PERF_FREQUENCIES = ["Daily", "Weekly", "Monthly", "Quarterly", "Continuous"]


def _synth_requirements(n: int) -> list[Requirement]:
    """Build n synthetic requirements with varied text for the perf test."""
    reqs = []
    for i in range(n):
        topic, text, source, mapping = _PERF_TOPICS[i % len(_PERF_TOPICS)]
        reqs.append(
            Requirement(
                id=f"PERF-REQ-{i:04d}",
                policy_id=f"PERF-POL-{i // 9:03d}",
                policy_title=f"{topic} Policy",
                number=i % 9 + 1,
                text=f"{text} (control instance {i}).",
                evidence_source=source,
                audit_frequency=_PERF_FREQUENCIES[i % len(_PERF_FREQUENCIES)],
                compliance_mappings=[mapping],
            )
        )
    return reqs


def _cmd_perf(args: argparse.Namespace) -> int:
    """Time the offline pipeline at the rubric's stated production scale.

    Synthesizes `--reqs` requirements (default 500) and `--n` evidence rows
    (default 5000) in memory, then times the scale-sensitive pipeline stages:
    map evidence to requirements, score compliance, audit corpus integrity.
    Synthesis is setup and is timed separately, not counted. Everything runs
    offline with the LLM adapter off.
    """
    import time

    print(
        f"Performance run: synthesizing {args.reqs} requirements + {args.n} evidence "
        f"rows (seed {args.seed})..."
    )
    gen_start = time.perf_counter()
    requirements = _synth_requirements(args.reqs)
    req_ids = [r.id for r in requirements]
    bench = generate_synthetic(n=args.n, seed=args.seed, valid_requirement_ids=req_ids)
    records = bench.records
    gen_secs = time.perf_counter() - gen_start
    print(
        f"  generated {len(requirements)} requirements + {len(records)} evidence rows "
        f"in {gen_secs:.2f}s (setup, not counted)"
    )
    print()

    stage_secs: dict[str, float] = {}

    t0 = time.perf_counter()
    links = map_evidence(records, requirements)
    stage_secs["map"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    score_corpus(requirements, records, links)
    stage_secs["score"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    audit_corpus(records, requirements)
    stage_secs["integrity"] = time.perf_counter() - t0

    total = sum(stage_secs.values())
    bar = 60.0
    print(f"Pipeline on {len(requirements)} requirements + {len(records)} evidence rows (LLM off):")
    for stage in ("map", "score", "integrity"):
        print(f"  {stage:<10}{stage_secs[stage]:>8.3f}s")
    print(f"  {'TOTAL':<10}{total:>8.3f}s")
    print()
    verdict = "PASS" if total < bar else "FAIL"
    print(f"  Bar: full pipeline < {bar:.0f}s. Measured {total:.3f}s -> {verdict}")
    return 0 if total < bar else 1


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

    score_p = sub.add_parser("score", help="map evidence + score compliance, both benches")
    score_p.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    score_p.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    score_p.add_argument("--out", type=Path, default=DEFAULT_SCORE_OUT)
    score_p.set_defaults(func=_cmd_score)

    report_p = sub.add_parser("report", help="write an auditor-ready JSON + PDF report")
    report_p.add_argument("--bench", choices=["sample", "synthetic"], default="sample")
    report_p.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    report_p.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    report_p.add_argument("--out", type=Path, default=Path("reports"))
    report_p.set_defaults(func=_cmd_report)

    serve_p = sub.add_parser(
        "serve",
        help="serve the single-page dashboard locally",
        description=(
            "Build the dashboard payload (mapping + scoring + narratives + integrity) "
            "and serve a single page at http://127.0.0.1:PORT with a JSON endpoint at "
            "/api/payload. Both benches load with a toggle. Use --write DIR to emit a "
            "self-contained index.html + dashboard_data.json that opens with no server "
            "(handy for screenshots). Runs offline, no API key."
        ),
    )
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--bench", choices=["sample", "synthetic"], default="synthetic",
                         help="which bench is shown first (both are available via the toggle)")
    serve_p.add_argument("--policies", type=Path, default=DEFAULT_POLICIES)
    serve_p.add_argument("--write", type=Path, default=None,
                         help="write a static, self-contained dashboard to this directory instead of serving")
    serve_p.set_defaults(func=_cmd_serve)

    synth_p = sub.add_parser("synth", help="(re)generate the synthetic bench")
    synth_p.add_argument("--out", type=Path, default=SYNTHETIC_DIR)
    synth_p.add_argument("--n", type=int, default=500)
    synth_p.add_argument("--seed", type=int, default=20260614)
    synth_p.set_defaults(func=_cmd_synth)

    collect_p = sub.add_parser(
        "collect",
        help="run the mock evidence collectors (CloudTrail + config snapshot)",
        description=(
            "Run the two mock collectors, which read committed sample exports and "
            "emit EvidenceRecord objects in the pipeline's shape, then show them "
            "linked to requirements. Mocked (file reads stand in for live APIs); "
            "see docs/COLLECTORS.md. Runs offline, no API key."
        ),
    )
    collect_p.set_defaults(func=_cmd_collect)

    perf_p = sub.add_parser(
        "perf",
        help="time the full pipeline on a large generated corpus",
        description=(
            "Generate a large synthetic corpus in memory and time the pipeline "
            "(parse + map + score + integrity) against the <60s scale bar. Runs "
            "offline, writes nothing, needs no API key."
        ),
    )
    perf_p.add_argument("--reqs", type=int, default=500, help="requirements to synthesize (default 500)")
    perf_p.add_argument("--n", type=int, default=5000, help="evidence rows to generate (default 5000)")
    perf_p.add_argument("--seed", type=int, default=20260614)
    perf_p.set_defaults(func=_cmd_perf)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
