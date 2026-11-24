"""Что модель возвращает по одному скриншоту."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mechanic = Literal[
    "Album", "Casual Casino", "Collection", "Core Duplicates", "Customization/Decoration", "Digging",
    "Expedition", "Fishing", "Gacha", "Lava Quest", "Login Calendar", "Lucky Wheel", "Monopoly",
    "Pick-a-Box/Card", "Race", "Tabletop", "Win Streak", "Leaderboard", "Team Event", "Pass", "Other",
]
Motivation = Literal[
    "Collecting", "Competitive", "Cooperative", "Customizing", "Gambling", "Sense of FOMO",
    "Sense of achievement", "Sense of novelty", "Unique occasion",
]
ScreenType = Literal[
    "event_intro", "event_progress", "leaderboard", "rewards", "event_offer", "event_gameplay",
    "regular_gameplay", "home_or_menu", "other",
]


class ScreenshotReading(BaseModel):
    """Разбор одного внутриигрового скриншота."""

    screen_type: ScreenType
    is_liveops_event: bool = Field(description="True when a limited-time LiveOps event screen is the main content of the screenshot.")
    event_name: str | None = Field(description="Event title exactly as written on screen, or null if no title is visible.")
    mechanics: list[Mechanic] = Field(description="Event mechanics, the main one first. Empty if not an event.")
    motivations: list[Motivation]
    has_leaderboard: bool
    time_left: str | None = Field(description="Timer text as shown, for example '2d 5h', or null.")
    rewards_visible: list[str] = Field(description="Short names of rewards visible on screen.")
    confidence: Literal["high", "medium", "low"]
    evidence: str = Field(description="One short sentence: what on the screen supports the answer.")
