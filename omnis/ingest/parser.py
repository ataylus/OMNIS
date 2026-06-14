"""Deterministic structural parser for policy_documents.txt.

The policy file is line-structured, not free prose: a header block of KEY: value
lines, then REQUIREMENT N markers, each followed by "- field: value" lines. The
parser is tolerant of the things the sample file actually does (CRLF endings, a
lowercase `scope:` field) but stays strictly structural. No NLP, no LLM. Field
names are matched case-insensitively; an LLM enrichment pass can come later.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from omnis.models import Requirement

# A requirement starts at "REQUIREMENT <n>:". Capture the number; the text runs
# to end of line (continuation lines before the first "- " field are appended).
_REQUIREMENT_RE = re.compile(r"^REQUIREMENT\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)
# A field line: "- name: value". Name is matched case-insensitively downstream.
_FIELD_RE = re.compile(r"^-\s*([^:]+?)\s*:\s*(.*)$")
# A header line in the policy block: "KEY: value".
_HEADER_RE = re.compile(r"^([A-Za-z_]+)\s*:\s*(.*)$")

# Principle-based phrasings that have no objective pass/fail criterion. A
# requirement that uses one of these and states no concrete threshold is
# ambiguous: an auditor has to interpret it. This is the "ambiguous requirement"
# edge case the brief asks us to surface at extraction time.
_VAGUE_TERMS = (
    "least privilege", "personal use", "as appropriate", "where appropriate",
    "as needed", "where feasible", "if applicable", "as necessary", "reasonable",
    "periodically", "from time to time", "adequate", "sufficient", "timely",
    "best effort", "as required",
)
# Concrete, testable criteria. If a requirement names one of these, it has an
# objective check and is not flagged, even if it also reads loosely.
_CONCRETE_RE = re.compile(
    r"\b(\d+\s*(?:days?|hours?|months?|years?|bit|bits)|aes-?\d+|tls\s*\d|"
    r"sha-?\d+|rsa-?\d+|annually|quarterly|monthly|weekly|daily|"
    r"multi-?factor|mfa)\b",
    re.IGNORECASE,
)


def classify_ambiguity(text: str) -> tuple[bool, str | None]:
    """Flag a requirement whose text states a principle but no measurable
    threshold. Returns (is_ambiguous, note)."""
    low = (text or "").lower()
    hit = next((term for term in _VAGUE_TERMS if term in low), None)
    if hit and not _CONCRETE_RE.search(text or ""):
        return True, (
            f'States a principle ("{hit}") with no measurable threshold; '
            f"compliance is a matter of auditor judgment, not an objective check."
        )
    return False, None


# Canonical field-name -> Requirement attribute. Keys are lowercased.
_FIELD_MAP = {
    "responsible": "responsible",
    "scope": "scope",
    "evidence source": "evidence_source",
    "audit frequency": "audit_frequency",
    "compliance mapping": "compliance_mappings",
}


def _normalize(text: str) -> str:
    """Collapse CRLF and lone CR into LF so line handling is uniform."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_header_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_policy_block(block: str) -> list[Requirement]:
    lines = block.split("\n")
    header: dict[str, str] = {}
    idx = 0
    # Read header lines until the first REQUIREMENT marker.
    while idx < len(lines):
        line = lines[idx]
        if _REQUIREMENT_RE.match(line.strip()):
            break
        m = _HEADER_RE.match(line.strip())
        if m:
            header[m.group(1).upper()] = m.group(2).strip()
        idx += 1

    policy_id = header.get("POLICY_ID", "").strip()
    policy_title = header.get("POLICY", "").strip()
    policy_version = header.get("VERSION") or None
    policy_status = header.get("STATUS") or None
    policy_last_updated = _parse_header_date(header.get("LAST_UPDATED", ""))

    requirements: list[Requirement] = []
    current_number: int | None = None
    current_text_parts: list[str] = []
    current_fields: dict[str, object] = {}

    def flush() -> None:
        if current_number is None:
            return
        req_text = " ".join(p.strip() for p in current_text_parts).strip()
        is_ambiguous, ambiguity_note = classify_ambiguity(req_text)
        req = Requirement(
            id=f"{policy_id}-R{current_number}",
            policy_id=policy_id,
            policy_title=policy_title,
            number=current_number,
            text=req_text,
            ambiguous=is_ambiguous,
            ambiguity_note=ambiguity_note,
            responsible=current_fields.get("responsible"),
            scope=current_fields.get("scope"),
            evidence_source=current_fields.get("evidence_source"),
            audit_frequency=current_fields.get("audit_frequency"),
            compliance_mappings=current_fields.get("compliance_mappings", []),
            policy_version=policy_version,
            policy_status=policy_status,
            policy_last_updated=policy_last_updated,
        )
        requirements.append(req)

    for line in lines[idx:]:
        stripped = line.strip()
        req_match = _REQUIREMENT_RE.match(stripped)
        if req_match:
            flush()
            current_number = int(req_match.group(1))
            current_text_parts = [req_match.group(2)]
            current_fields = {}
            continue
        if current_number is None:
            continue
        field_match = _FIELD_RE.match(stripped)
        if field_match:
            name = field_match.group(1).strip().lower()
            value = field_match.group(2).strip()
            attr = _FIELD_MAP.get(name)
            if attr == "compliance_mappings":
                current_fields[attr] = [
                    part.strip() for part in value.split(",") if part.strip()
                ]
            elif attr is not None:
                current_fields[attr] = value
            continue
        # A non-field, non-marker line before any field is a wrapped requirement
        # sentence; append it to the requirement text.
        if stripped and not current_fields:
            current_text_parts.append(stripped)

    flush()
    return requirements


def parse_policies(path: str | Path) -> list[Requirement]:
    """Parse a policy document file into a flat list of Requirement objects.

    Policies are separated by a line that is exactly "---". The sample file
    yields exactly 9 requirements across 3 policies.
    """
    raw = Path(path).read_text(encoding="utf-8")
    text = _normalize(raw)
    blocks = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    requirements: list[Requirement] = []
    for block in blocks:
        if block.strip():
            requirements.extend(_parse_policy_block(block))
    return requirements
