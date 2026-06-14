"""Policy ingestion: deterministic structural parser for policy documents."""

from omnis.ingest.parser import classify_ambiguity, parse_policies

__all__ = ["parse_policies", "classify_ambiguity"]
