"""tests/test_scoring.py — Tests du module de scoring déterministe."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.analyzer.scoring import (
    check_disqualification,
    compute_score,
    score_deadline_feasibility,
    score_geography,
    score_partner,
    score_theme,
    score_vehicle,
)
from src.config import (
    AnalyzedOpportunity,
    Decision,
    OpportunityType,
    RawOpportunity,
    SourceKind,
    Theme,
)
from src.config.settings import get_ugfs_profile


@pytest.fixture
def profile():
    return get_ugfs_profile()


@pytest.fixture
def base_raw():
    return RawOpportunity(
        title="Climate Adaptation Fund — Tunisia 2026",
        url="https://example.org/ao/123",
        source="test",
        source_kind=SourceKind.GOOGLE_CSE,
        raw_text="Lorem ipsum about climate adaptation in Tunisia, GIZ partner.",
    )


@pytest.fixture
def base_analyzed():
    return AnalyzedOpportunity(
        title="Climate Adaptation Fund — Tunisia 2026",
        summary_executive="Programme de financement adaptation climat Tunisie.",
        opportunity_type=OpportunityType.GRANT,
        theme=Theme.GREEN,
        geographies=["Tunisia", "North Africa"],
        sectors=["climate adaptation", "renewable energy"],
        eligibility_summary="Asset managers, fund managers, climate funds",
        deadline=date.today() + timedelta(days=45),
        ticket_size_usd=2_000_000,
        languages=["fr", "en"],
        why_interesting="Match parfait avec Tunisia Green Fund",
        preliminary_decision=Decision.PENDING,
        decision_rationale="Géo + thème + véhicule alignés",
        partners_mentioned=["GIZ", "Adaptation Fund"],
        vehicle_match="TGF",
        submission_url="https://example.org/apply",
    )


def test_geography_primary(profile):
    pts, why = score_geography(["Tunisia", "Egypt"], profile)
    assert pts == 100
    assert "primaire" in why.lower()


def test_geography_secondary(profile):
    pts, _ = score_geography(["Senegal"], profile)
    assert pts == 50


def test_geography_europe(profile):
    pts, _ = score_geography(["France"], profile)
    assert pts == 25


def test_geography_empty(profile):
    pts, _ = score_geography([], profile)
    assert pts == 0


def test_theme_green_max(profile):
    # green pèse 50 dans le profil → 50/50 = 100%
    pts, _ = score_theme("green", profile)
    assert pts == 100


def test_theme_unknown(profile):
    pts, _ = score_theme("unknown", profile)
    assert 0 < pts < 100


def test_vehicle_match_explicit(base_raw, base_analyzed, profile):
    pts, why = score_vehicle(base_analyzed, base_raw.raw_text, profile)
    assert pts == 100
    assert "TGF" in why or "Tunisia Green Fund" in why


def test_vehicle_no_match(base_raw, base_analyzed, profile):
    base_analyzed.vehicle_match = None
    base_raw.raw_text = "Random unrelated content about widgets"
    base_analyzed.title = "Widget RFP"
    base_analyzed.summary_executive = "Buying widgets"
    base_analyzed.eligibility_summary = "anyone"
    base_analyzed.sectors = []
    pts, _ = score_vehicle(base_analyzed, base_raw.raw_text, profile)
    assert pts == 0


def test_partner_priority(profile):
    pts, why = score_partner(["GIZ", "Random Org"], profile)
    assert pts == 100


def test_partner_empty(profile):
    pts, _ = score_partner([], profile)
    assert pts == 0


def test_deadline_far():
    pts, _ = score_deadline_feasibility(date.today() + timedelta(days=60))
    assert pts == 100


def test_deadline_urgent():
    pts, _ = score_deadline_feasibility(date.today() + timedelta(days=3))
    assert pts == 20


def test_deadline_rolling():
    pts, _ = score_deadline_feasibility(None)
    assert pts == 70


def test_deadline_passed():
    pts, _ = score_deadline_feasibility(date.today() - timedelta(days=10))
    assert pts == 0


def test_disqualification_passed_deadline(base_analyzed, profile):
    base_analyzed.deadline = date.today() - timedelta(days=5)
    is_dq, reason = check_disqualification(base_analyzed, profile)
    assert is_dq
    assert "déjà passée" in reason.lower() or "dépassée" in reason.lower()


def test_disqualification_strict_geo(base_analyzed, profile):
    base_analyzed.geographies = ["North America"]
    is_dq, reason = check_disqualification(base_analyzed, profile)
    assert is_dq


def test_disqualification_eligibility(base_analyzed, profile):
    base_analyzed.eligibility_summary = "Individual consultant only"
    is_dq, _ = check_disqualification(base_analyzed, profile)
    assert is_dq


def test_compute_score_high_match(base_raw, base_analyzed):
    scored = compute_score(base_raw, base_analyzed, similarity_to_past_go=0.5)
    assert scored.score >= 70, f"Got {scored.score}, expected ≥70"
    assert scored.is_urgent is False
    assert scored.analyzed.preliminary_decision == Decision.GO
    # Fingerprint déterministe
    scored2 = compute_score(base_raw, base_analyzed, similarity_to_past_go=0.5)
    assert scored.fingerprint == scored2.fingerprint


def test_compute_score_dq(base_raw, base_analyzed):
    base_analyzed.deadline = date.today() - timedelta(days=5)
    scored = compute_score(base_raw, base_analyzed)
    assert scored.score == 0
    assert scored.status == "NO_GO"


def test_compute_score_urgent(base_raw, base_analyzed):
    base_analyzed.deadline = date.today() + timedelta(days=3)
    scored = compute_score(base_raw, base_analyzed)
    assert scored.is_urgent is True


def test_similarity_boost_applied(base_raw, base_analyzed):
    # Sans boost
    scored_no = compute_score(base_raw, base_analyzed, similarity_to_past_go=0.5)
    # Avec boost (similarity au-dessus du seuil 0.85)
    scored_yes = compute_score(base_raw, base_analyzed, similarity_to_past_go=0.92)
    assert scored_yes.score > scored_no.score
