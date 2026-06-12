"""Tests for the audit-frequency-driven freshness model."""

from datetime import date

import pytest

from omnis.freshness import (
    DEFAULT_WINDOW_DAYS,
    REFERENCE_DATE,
    freshness_score,
    is_stale,
    record_age_days,
    staleness_window,
)
from omnis.models import EvidenceRecord


def make_record(**overrides):
    base = dict(
        evidence_id="E0",
        requirement_id="R1",
        requirement_description="d",
        framework="GDPR",
        evidence_type="config",
        collected_by="t",
        collector_email="t@c.com",
        collection_date=date(2026, 1, 1),
        freshness_days=10,
        evidence_summary="s",
        status="Approved",
    )
    base.update(overrides)
    return EvidenceRecord(**base)


def test_reference_date_is_shared_constant():
    # Freshness owns REFERENCE_DATE; the integrity auditor reuses the same value.
    from omnis.integrity import checks

    assert REFERENCE_DATE == date(2026, 4, 15)
    assert checks.REFERENCE_DATE is REFERENCE_DATE


def test_staleness_window_per_frequency():
    assert staleness_window("Daily") == 1
    assert staleness_window("Weekly") == 7
    assert staleness_window("Monthly") == 30
    assert staleness_window("Quarterly") == 90
    assert staleness_window("Continuous") == 1
    # Unknown frequency falls back to the 90-day default; casing is tolerated.
    assert staleness_window("quarterly") == 90
    assert staleness_window(None) == DEFAULT_WINDOW_DAYS
    assert staleness_window("bogus") == DEFAULT_WINDOW_DAYS


def test_is_stale_boundary():
    # Monthly window is 30 days: 30 is fresh, 31 is stale.
    assert is_stale(31, "Monthly") is True
    assert is_stale(30, "Monthly") is False
    assert is_stale(None, "Monthly") is False  # unknown age not asserted stale


def test_freshness_score_decay_and_halflife():
    # Score is 1.0 at age 0 and halves every window (half-life == window).
    assert freshness_score(0, "Monthly") == 1.0
    assert freshness_score(30, "Monthly") == pytest.approx(0.5)
    assert freshness_score(60, "Monthly") == pytest.approx(0.25)
    # Monotonically decreasing with age.
    assert freshness_score(10, "Monthly") > freshness_score(20, "Monthly")
    # Unknown age cannot be claimed fresh.
    assert freshness_score(None, "Monthly") == 0.0


def test_record_age_uses_freshness_days_authoritatively():
    # freshness_days disagrees with the date math on purpose; the model trusts
    # freshness_days (the date columns are known to be internally inconsistent).
    rec = make_record(collection_date=date(2026, 1, 1), freshness_days=10)
    assert record_age_days(rec) == 10  # not (2026-04-15 - 2026-01-01) == 104


def test_record_age_falls_back_to_dates_when_freshness_missing():
    rec = make_record(collection_date=date(2026, 4, 5), freshness_days=None)
    assert record_age_days(rec) == (REFERENCE_DATE - date(2026, 4, 5)).days


def test_record_age_none_when_nothing_known():
    rec = make_record(collection_date=None, freshness_days=None)
    assert record_age_days(rec) is None
