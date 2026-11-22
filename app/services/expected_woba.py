"""Statcast/Savant-style full expected wOBA on terminal plate appearances.

Statcast's estimated_woba_using_speedangle measures batted-ball quality only:
its missing value for a strikeout, walk, or HBP does NOT make the outcome
unscorable. Full xwOBA uses:
  * 0 for strikeouts (and strikeout double plays);
  * Savant-sourced outcome wOBA weights for unintentional BB and HBP;
  * Statcast's tracked contact estimate for remaining eligible PA endings.

Use Savant-verified outcome weights where the wOBA refresh exists, otherwise
use the imported Statcast woba_value (both stored with the pitch). Do not
fabricate a year-specific weight when neither source is present. The actual
wOBA denominator is used when it was verified and otherwise falls back to
event classification. All aggregations may therefore report their scoring
coverage without silently interpreting untracked contact as zero.
"""

from __future__ import annotations

from sqlalchemy import and_, case, func, or_

from app.models import Pitch

# These outcomes do not enter Savant's ordinary wOBA denominator.
EXCLUDED_XWOBA_EVENTS = (
    "intent_walk",
    "sac_bunt",
    "sac_bunt_double_play",
    "catcher_interf",
    "truncated_pa",
)
STRIKEOUT_EVENTS = ("strikeout", "strikeout_double_play")
FREE_PASS_EVENTS = ("walk", "hit_by_pitch")


def full_xwoba_expressions():
    """Return (eligible PA, expected wOBA weight), both SQL expressions."""
    event = func.lower(func.trim(func.coalesce(Pitch.events, "")))
    eligible = and_(
        event != "",
        event.notin_(EXCLUDED_XWOBA_EVENTS),
        # When official Savant denominator is present, trust its eligibility.
        or_(Pitch.savant_woba_denominator.is_(None), Pitch.savant_woba_denominator == 1),
    )
    # Ignore any stray contact estimate on BB, HBP, or strikeout rows.
    # Non-contact outcomes must use their actual, weighted PA contribution.
    value = case(
        (event.in_(STRIKEOUT_EVENTS), 0.0),
        (
            event.in_(FREE_PASS_EVENTS),
            func.coalesce(Pitch.savant_woba_numerator, Pitch.woba_value),
        ),
        else_=Pitch.estimated_woba,
    )
    return eligible, value
