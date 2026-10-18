"""Targeted tests for the deterministic overlay renderer."""

from __future__ import annotations

from datetime import datetime

from renderer.renderer import build_card_id, render_narration_card, render_spotlight_card, render_stat_card
from shared.models import GlossEn, NarratorResponse


def test_build_card_id_is_deterministic_for_llm_and_stat_cards():
    first = build_card_id(card_type="key_moment", profile_key="match-1.sw.casual.home", moment_id="match-1-km-0001")
    second = build_card_id(card_type="key_moment", profile_key="match-1.sw.casual.home", moment_id="match-1-km-0001")
    stat = build_card_id(card_type="stat", profile_key="match-1.sw.casual.home", period=1, minute=45)

    assert first == second
    assert first.startswith("card-key_moment-")
    assert stat.startswith("card-stat-")


def test_render_narration_card_builds_overlay_card_without_display_from_field():
    response = NarratorResponse(
        profile_key="match-1.sw.casual.home",
        moment_id="match-1-km-0001",
        headline="Gool!",
        body="Amina Kivuva anafunga dakika ya 88.",
        gloss_en=GlossEn(headline="Goal!", body="Amina Kivuva scores in the 88th minute."),
        generated_at=datetime(2026, 10, 1, 12, 0, 0),
    )

    card = render_narration_card(
        response=response,
        match_clock={"period": 2, "minute": 43, "second": 0},
        match_seconds=1230.0,
        card_type="key_moment",
        priority=1,
        team_ref="Ngome United",
        player_ref="Amina Kivuva",
    )

    assert card.card_type == "key_moment"
    assert card.display_duration_ms == 6000
    assert card.match_seconds == 1230.0
    assert "display_from" not in card.__dict__
    assert card.text["sw"]["headline"] == "Gool!"


def test_render_stat_card_matches_template_contract():
    card = render_stat_card(
        profile_key="match-1.en.casual.home",
        period=1,
        minute=15,
        language="en",
        stat_label="Possession",
        stat_value="58%",
        team_ref="Ngome United",
    )

    assert card.card_type == "stat"
    assert card.stat_payload == {"label": "Possession", "value": "58%"}
    assert card.display_duration_ms == 4000
    assert card.match_clock == {"period": 1, "minute": 15, "second": 0}


def test_render_spotlight_card_uses_player_reference_and_event_id():
    card = render_spotlight_card(
        profile_key="match-1.sw.casual.home",
        player="Amina Kivuva",
        team_ref="Ngome United",
        event_id="match-1-000123",
        language="sw",
    )

    assert card.card_type == "player_spotlight"
    assert card.player_ref == "Amina Kivuva"
    assert card.evidence_event_ids == ["match-1-000123"]
    assert card.match_seconds == 0.0
