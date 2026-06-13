"""Layered evidence-to-requirement linker.

Layers run in order and stop at the first success; every link carries a method
tag and a confidence:

  a) exact_id      requirement_id equals a known requirement id.
  b) framework_rule deterministic match on framework + evidence_type against the
                   requirement's compliance frameworks and evidence_source.
  c) tfidf         offline TF-IDF cosine similarity between the evidence text and
                   the requirement text, above a documented similarity floor.

Below the floor the record is UNMAPPED, which is a reportable outcome (it feeds
the "missing evidence" and INCOMPLETE_MAPPING stories), not an error. The TF-IDF
layer is a small pure-Python implementation so the linker runs offline with no
extra dependencies. A low-margin link can later be sent to an LLM for
adjudication through the `adjudicate_with_llm` hook, which is a deliberate no-op
in offline mode.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from omnis.models import EvidenceLink, EvidenceRecord, Requirement

# TF-IDF cosine below this is treated as no confident match -> UNMAPPED.
SIM_FLOOR = 0.10

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "and", "or", "of", "to", "in", "a", "an", "for", "with", "be", "is",
    "are", "must", "all", "at", "on", "any", "this", "that", "as", "by",
}

# Map a compliance-mapping string or evidence framework to a canonical framework
# key, so framework_rule can compare them. Order matters (first hit wins).
_FRAMEWORK_PREFIXES = [
    ("gdpr", "GDPR"),
    ("nist", "NIST"),
    ("pci", "PCI-DSS"),
    ("iso", "ISO27001"),
    ("sox", "SOX"),
    ("cis", "CIS"),
    ("hipaa", "HIPAA"),
]


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS and len(t) > 1]


def _framework_key(text: str) -> str | None:
    low = (text or "").lower().replace(" ", "")
    for prefix, key in _FRAMEWORK_PREFIXES:
        if low.startswith(prefix):
            return key
    return None


def _requirement_frameworks(req: Requirement) -> set[str]:
    keys = set()
    for mapping in req.compliance_mappings:
        key = _framework_key(mapping)
        if key:
            keys.add(key)
    return keys


def _requirement_doc(req: Requirement) -> str:
    parts = [req.text, req.scope or "", req.evidence_source or "", req.policy_title]
    parts.extend(req.compliance_mappings)
    return " ".join(parts)


def _evidence_doc(record: EvidenceRecord) -> str:
    return " ".join(
        [
            record.requirement_description,
            record.evidence_summary,
            record.evidence_type.replace("_", " "),
            record.framework,
        ]
    )


class TfidfIndex:
    """Tiny TF-IDF index over the requirement documents, cosine query offline."""

    def __init__(self, requirements: list[Requirement]) -> None:
        self.requirements = requirements
        docs = [_tokens(_requirement_doc(r)) for r in requirements]
        n = len(docs)
        df: Counter[str] = Counter()
        for tokens in docs:
            df.update(set(tokens))
        # Smoothed idf so a term in every doc still contributes a little.
        self.idf = {term: math.log((1 + n) / (1 + dfreq)) + 1.0 for term, dfreq in df.items()}
        self.doc_vectors = [self._vector(tokens) for tokens in docs]

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        vec = {term: count * self.idf.get(term, 0.0) for term, count in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm == 0:
            return {}
        return {term: v / norm for term, v in vec.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(weight * b.get(term, 0.0) for term, weight in a.items())

    def best_match(self, text: str) -> tuple[int, float]:
        """Return (index of best requirement, cosine similarity)."""
        query = self._vector(_tokens(text))
        best_idx, best_sim = -1, 0.0
        for idx, doc_vec in enumerate(self.doc_vectors):
            sim = self._cosine(query, doc_vec)
            if sim > best_sim:
                best_idx, best_sim = idx, sim
        return best_idx, best_sim


def _exact(record: EvidenceRecord, by_id: dict[str, Requirement]) -> EvidenceLink | None:
    req = by_id.get(record.requirement_id)
    if req is None:
        return None
    return EvidenceLink(
        evidence_id=record.evidence_id,
        requirement_id=req.id,
        method="exact_id",
        confidence=1.0,
        mapped=True,
    )


def _framework_rule(
    record: EvidenceRecord, requirements: list[Requirement], req_frameworks: dict[str, set[str]]
) -> EvidenceLink | None:
    ev_framework = _framework_key(record.framework) or record.framework
    ev_type_tokens = set(_tokens(record.evidence_type.replace("_", " ")))
    best_req, best_overlap = None, 0
    for req in requirements:
        if ev_framework not in req_frameworks[req.id]:
            continue
        source_tokens = set(_tokens(req.evidence_source or ""))
        overlap = len(ev_type_tokens & source_tokens)
        if overlap > best_overlap:
            best_req, best_overlap = req, overlap
    if best_req is None or best_overlap == 0:
        return None
    return EvidenceLink(
        evidence_id=record.evidence_id,
        requirement_id=best_req.id,
        method="framework_rule",
        confidence=round(min(0.8, 0.55 + 0.1 * best_overlap), 3),
        mapped=True,
    )


def _tfidf(record: EvidenceRecord, requirements: list[Requirement], index: TfidfIndex) -> EvidenceLink:
    idx, sim = index.best_match(_evidence_doc(record))
    if idx < 0 or sim < SIM_FLOOR:
        return EvidenceLink(
            evidence_id=record.evidence_id,
            requirement_id=None,
            method="unmapped",
            confidence=round(max(sim, 0.0), 3),
            mapped=False,
        )
    return EvidenceLink(
        evidence_id=record.evidence_id,
        requirement_id=requirements[idx].id,
        method="tfidf",
        confidence=round(sim, 3),
        mapped=True,
    )


def map_evidence(
    records: list[EvidenceRecord], requirements: list[Requirement]
) -> list[EvidenceLink]:
    """Link every evidence record to a requirement (or UNMAPPED), layered."""
    by_id = {req.id: req for req in requirements}
    req_frameworks = {req.id: _requirement_frameworks(req) for req in requirements}
    index = TfidfIndex(requirements)
    links: list[EvidenceLink] = []
    for record in records:
        link = (
            _exact(record, by_id)
            or _framework_rule(record, requirements, req_frameworks)
            or _tfidf(record, requirements, index)
        )
        links.append(link)
    return links


def adjudicate_with_llm(
    record: EvidenceRecord, candidates: list[Requirement], mode: str = "off"
) -> EvidenceLink | None:
    """LLM adjudication hook for low-margin links. No-op in offline mode.

    This is the single named seam where an LLM would break ties between close
    candidate requirements. In `off` mode (the judge default) it returns None and
    the deterministic layers stand. A later block wires `mode="cached"/"live"`
    through omnis/llm.py; nothing here ever requires an API key.
    """
    return None
