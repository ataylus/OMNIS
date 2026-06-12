"""Evaluation harness: precision/recall/F1 for evidence anomaly detection.

DOCUMENTED ASSUMPTION: a blank anomaly_marker is treated as a negative (not an
anomaly). The advertised label distribution (~70% anomalous) conflicts with the
markers embedded in the provided CSV (26%). We grade under this stated
assumption and expose --labels so that if the organizers release the advertised
evidence_labels.csv mid-event we re-grade instantly without code changes.

Two metric views are produced:
  - binary: is_anomaly (any non-blank marker) vs detector firing (any class).
  - per-class: precision/recall/F1 for each anomaly class, treating both truth
    and prediction as single-label (the class name, or "NONE").
Plus a confusion matrix over class labels (true -> predicted counts).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import pandas as pd

from omnis.models import EvalResult, EvidenceRecord, Prediction

NEGATIVE = "NONE"


class Detector(Protocol):
    name: str

    def predict(self, record: EvidenceRecord) -> Prediction | None: ...


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return precision, recall, f1


def load_label_overrides(path: str | Path) -> dict[str, str | None]:
    """Read an external labels file -> {evidence_id: anomaly_type or None}.

    Expected columns: evidence_id, is_anomaly, anomaly_type. is_anomaly is read
    truthily (1/true/yes). When is_anomaly is false the truth becomes None even
    if anomaly_type is populated.
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    required = {"evidence_id", "is_anomaly", "anomaly_type"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"labels file missing columns: {sorted(missing)}")
    overrides: dict[str, str | None] = {}
    for row in frame.to_dict(orient="records"):
        is_anomaly = str(row["is_anomaly"]).strip().lower() in {"1", "true", "yes", "y"}
        anomaly_type = str(row["anomaly_type"]).strip()
        overrides[str(row["evidence_id"]).strip()] = (
            (anomaly_type or "ANOMALY") if is_anomaly else None
        )
    return overrides


def _truth_label(
    record: EvidenceRecord, overrides: dict[str, str | None] | None
) -> str | None:
    """Resolve the ground-truth class for a record (None == negative)."""
    if overrides is not None and record.evidence_id in overrides:
        return overrides[record.evidence_id]
    return record.anomaly_marker  # already None when blank


def evaluate(
    records: list[EvidenceRecord],
    detector: Detector,
    overrides: dict[str, str | None] | None = None,
    label_source: str = "anomaly_marker",
) -> EvalResult:
    """Score a detector against ground truth, binary and per-class."""
    tp = fp = fn = tn = 0
    class_tp: dict[str, int] = {}
    class_pred: dict[str, int] = {}
    class_true: dict[str, int] = {}
    confusion: dict[str, dict[str, int]] = {}

    for record in records:
        truth = _truth_label(record, overrides)
        prediction = detector.predict(record)
        pred = prediction.anomaly_class if prediction is not None else None

        truth_pos = truth is not None
        pred_pos = pred is not None
        if truth_pos and pred_pos:
            tp += 1
        elif pred_pos and not truth_pos:
            fp += 1
        elif truth_pos and not pred_pos:
            fn += 1
        else:
            tn += 1

        truth_label = truth or NEGATIVE
        pred_label = pred or NEGATIVE
        if truth_pos:
            class_true[truth_label] = class_true.get(truth_label, 0) + 1
        if pred_pos:
            class_pred[pred_label] = class_pred.get(pred_label, 0) + 1
        if pred_pos and truth_pos and pred_label == truth_label:
            class_tp[pred_label] = class_tp.get(pred_label, 0) + 1
        confusion.setdefault(truth_label, {})
        confusion[truth_label][pred_label] = confusion[truth_label].get(pred_label, 0) + 1

    precision, recall, f1 = _prf(tp, fp, fn)

    per_class: dict[str, dict[str, float]] = {}
    for cls in sorted(set(class_true) | set(class_pred)):
        c_tp = class_tp.get(cls, 0)
        c_pred = class_pred.get(cls, 0)
        c_true = class_true.get(cls, 0)
        c_precision, c_recall, c_f1 = _prf(c_tp, c_pred - c_tp, c_true - c_tp)
        per_class[cls] = {
            "precision": c_precision,
            "recall": c_recall,
            "f1": c_f1,
            "support": float(c_true),
            "predicted": float(c_pred),
        }

    return EvalResult(
        mode="binary+per_class",
        detector=detector.name,
        label_source=label_source,
        total=len(records),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=precision,
        recall=recall,
        f1=f1,
        per_class=per_class,
        confusion=confusion,
    )


def save_result(result: EvalResult, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.model_dump(), indent=2), encoding="utf-8")


def format_result(result: EvalResult) -> str:
    """Render an EvalResult as a readable aligned table."""
    lines: list[str] = []
    lines.append(f"Detector:     {result.detector}")
    lines.append(f"Label source: {result.label_source}")
    lines.append(f"Records:      {result.total}")
    lines.append("")
    lines.append("Binary (is_anomaly):")
    lines.append(
        f"  TP={result.tp}  FP={result.fp}  FN={result.fn}  TN={result.tn}"
    )
    lines.append(
        f"  precision={result.precision:.3f}  recall={result.recall:.3f}  "
        f"f1={result.f1:.3f}"
    )
    lines.append("")
    lines.append("Per-class:")
    header = f"  {'class':<22}{'prec':>7}{'rec':>7}{'f1':>7}{'support':>9}{'pred':>7}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for cls, m in result.per_class.items():
        lines.append(
            f"  {cls:<22}{m['precision']:>7.3f}{m['recall']:>7.3f}{m['f1']:>7.3f}"
            f"{int(m['support']):>9}{int(m['predicted']):>7}"
        )
    lines.append("")
    lines.append("Confusion (true -> predicted):")
    pred_labels = sorted({p for row in result.confusion.values() for p in row})
    corner = "true\\pred"
    head = "  " + f"{corner:<22}" + "".join(f"{p:>14}" for p in pred_labels)
    lines.append(head)
    for true_label in sorted(result.confusion):
        row = result.confusion[true_label]
        cells = "".join(f"{row.get(p, 0):>14}" for p in pred_labels)
        lines.append(f"  {true_label:<22}{cells}")
    return "\n".join(lines)
