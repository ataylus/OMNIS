"""Audit-frequency-driven freshness model.

Each requirement's Audit Frequency (Daily/Weekly/Monthly/Quarterly/Continuous)
sets how long its evidence stays current. Evidence older than that window is
stale; a 0..1 decay score expresses how much trust has bled away with age.

AUTHORITATIVE AGE FIELD: we treat the `freshness_days` column as the source of
truth for record age, not (reference_date - collection_date). The Block 1
integrity audit found the date columns internally inconsistent (review_date
before collection_date in 239 of 500 rows; freshness_days disagreeing with the
date arithmetic in 455 of 500). Picking one authoritative field keeps freshness
deterministic and avoids propagating the corrupted date math. When
`freshness_days` is missing we fall back to the date arithmetic against a fixed
REFERENCE_DATE so results stay reproducible (never wall-clock now).
"""

from __future__ import annotations

from datetime import date

from omnis.models import EvidenceRecord

# Single audit "as of" date, shared across freshness and the integrity auditor.
# Fixed, not wall-clock, so every run and test is deterministic. Chosen to match
# the problem statement's example generated date.
REFERENCE_DATE = date(2026, 4, 15)

# Audit frequency -> staleness window in days. Evidence older than its window is
# stale. The window also serves as the half-life for the decay score.
FREQUENCY_WINDOWS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "continuous": 1,
}

# Default window when the audit frequency is unknown. Matches the problem
# statement's blanket definition of stale ("older than 90 days").
DEFAULT_WINDOW_DAYS = 90


def normalize_frequency(frequency: str | None) -> str:
    return (frequency or "").strip().lower()


def staleness_window(frequency: str | None) -> int:
    """Return the staleness window in days for an audit frequency."""
    return FREQUENCY_WINDOWS.get(normalize_frequency(frequency), DEFAULT_WINDOW_DAYS)


def record_age_days(
    record: EvidenceRecord, reference_date: date = REFERENCE_DATE
) -> int | None:
    """Age of a record in days. freshness_days is authoritative; see module docstring."""
    if record.freshness_days is not None:
        return record.freshness_days
    if record.collection_date is not None:
        return (reference_date - record.collection_date).days
    return None


def freshness_score(
    age_days: int | None,
    frequency: str | None = None,
    window_days: int | None = None,
) -> float:
    """Map age to a 0..1 freshness score via exponential decay.

    The score is 1.0 at age 0 and halves every `window_days` (the audit
    frequency's window, or DEFAULT_WINDOW_DAYS). Unknown age scores 0.0 because
    an unverifiable age cannot be claimed as fresh.
    """
    if age_days is None:
        return 0.0
    half_life = max(window_days if window_days is not None else staleness_window(frequency), 1)
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life)


def is_stale(
    age_days: int | None,
    frequency: str | None = None,
    window_days: int | None = None,
) -> bool:
    """True when a record is older than its staleness window.

    Age alone; approval state is a status concern handled by the detector. An
    unknown age is not asserted stale (we do not flag what we cannot measure).
    """
    if age_days is None:
        return False
    window = window_days if window_days is not None else staleness_window(frequency)
    return age_days > window
