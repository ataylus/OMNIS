"""Evaluation harness: precision/recall/F1 vs ground-truth anomaly markers."""

from omnis.evaluation.baseline import BaselineDetector
from omnis.evaluation.harness import (
    evaluate,
    format_result,
    load_label_overrides,
    save_result,
)

__all__ = [
    "BaselineDetector",
    "evaluate",
    "format_result",
    "load_label_overrides",
    "save_result",
]
