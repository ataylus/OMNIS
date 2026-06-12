"""Seeded synthetic evidence corpus with ground-truth labels by construction."""

from omnis.synthesis.generator import (
    DEFAULT_N,
    DEFAULT_SEED,
    SyntheticBench,
    generate_synthetic,
    load_synthetic_bench,
    load_valid_requirement_ids,
    materialize,
)

__all__ = [
    "DEFAULT_N",
    "DEFAULT_SEED",
    "SyntheticBench",
    "generate_synthetic",
    "load_synthetic_bench",
    "load_valid_requirement_ids",
    "materialize",
]
