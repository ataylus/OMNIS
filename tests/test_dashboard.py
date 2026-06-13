"""Tests for the dashboard payload builder and the ask-box filter."""

import json

from omnis.dashboard import build_dashboard_data, filter_requirements
from omnis.dashboard.server import render_page


def test_build_dashboard_data_both_benches():
    data = build_dashboard_data()
    assert "sample" in data and "synthetic" in data
    # The provided sample carries 3 policies / 9 requirements; the synthetic
    # bench carries the fuller 6-policy / 15-requirement scope.
    expected_requirements = {"sample": 9, "synthetic": 15}
    for bench in ("sample", "synthetic"):
        p = data[bench]
        assert p is not None, f"{bench} payload missing"
        for key in ("bench", "generated", "summary", "requirements", "integrity_findings"):
            assert key in p
        assert len(p["requirements"]) == expected_requirements[bench]
        for key in ("omniscience_index", "automation_rate", "total_evidence", "status_breakdown"):
            assert key in p["summary"]
        first = p["requirements"][0]
        for key in ("requirement_id", "status", "confidence", "evidence_count", "evidence_ids", "rationale", "narrative"):
            assert key in first


def test_payload_is_json_serializable():
    data = build_dashboard_data()
    text = json.dumps(data)  # must not raise
    assert "omniscience_index" in text


def test_render_page_inlines_data_and_is_self_contained():
    data = build_dashboard_data()
    html = render_page(data)
    assert "const OMNIS_DATA = null;" not in html  # sentinel replaced
    assert "const OMNIS_DATA = {" in html
    assert "Omniscience Index" in html


def test_render_page_initial_bench_synthetic():
    data = build_dashboard_data()
    html = render_page(data, initial_bench="synthetic")
    assert 'let bench = "synthetic";' in html


def _reqs():
    return build_dashboard_data()["sample"]["requirements"]


def test_filter_empty_returns_all():
    reqs = _reqs()
    assert len(filter_requirements(reqs, "")) == len(reqs)
    assert len(filter_requirements(reqs, "   ")) == len(reqs)


def test_filter_show_gaps_returns_only_gaps():
    reqs = _reqs()
    result = filter_requirements(reqs, "show gaps")
    assert result, "expected at least one GAP requirement on the sample bench"
    assert all(r["status"] == "GAP" for r in result)


def test_filter_unknown_returns_only_unknown():
    reqs = _reqs()
    result = filter_requirements(reqs, "unknown")
    assert result
    assert all(r["status"] == "UNKNOWN" for r in result)


def test_filter_text_term_encryption():
    reqs = _reqs()
    result = filter_requirements(reqs, "encryption")
    assert result
    # Every match mentions encryption somewhere in its searchable text.
    for r in result:
        blob = (r["requirement_id"] + r["text"] + r["rationale"] + r["narrative"]).lower()
        assert "encryption" in blob
    # The encryption-policy requirements are POL-ENC-*.
    assert any(r["requirement_id"].startswith("POL-ENC-001") for r in result)


def test_filter_status_and_text_combined():
    reqs = _reqs()
    # A status word plus a free-text term: both constraints apply (AND).
    result = filter_requirements(reqs, "unknown access")
    for r in result:
        assert r["status"] == "UNKNOWN"
        blob = (r["requirement_id"] + r["text"] + r["rationale"] + r["narrative"]).lower()
        assert "access" in blob
