"""Классификация LiveOps-событий.

Механики и мотивации взяты из методики AppMagic (Casual LiveOps Report H1 2025,
LiveOps & Updates Calendar). Определения с пометкой «AppMagic» процитированы из
отчёта, остальные написаны по смыслу названия механики.
"""

from __future__ import annotations

MECHANICS: dict[str, str] = {
    "Album": "AppMagic: completing an album with collectibles (cards, stickers, etc.).",
    "Casual Casino": "AppMagic: simplified casino mechanics without real money that are not Lucky Wheel, Tabletop, Monopoly or Gacha (slots, Plinko, lotto, coin pushers).",
    "Collection": "Players collect event items while playing (during levels or tasks) to fill a progress bar or reach milestones with rewards.",
    "Core Duplicates": "AppMagic: event gameplay that is fully or almost identical to the core gameplay (special event levels on the core board).",
    "Customization/Decoration": "Players decorate or customize an area, room, avatar or item as the event goal.",
    "Digging": "AppMagic: players excavate tiles in a specific area to uncover items or rewards.",
    "Expedition": "A separate adventure or journey map with its own stages, often a story trip to a new location.",
    "Fishing": "Fishing-themed mini-game: catching fish or items with a rod or net.",
    "Gacha": "Players spend currency or tickets on random draws (capsules, gacha machines) for collectibles.",
    "Lava Quest": "AppMagic: passing consecutive stages with a restriction (time limit, mandatory win streak); typically a group competition where the prize pool is split among players who complete all stages.",
    "Login Calendar": "Rewards for logging in on consecutive days (daily calendar, advent calendar).",
    "Lucky Wheel": "Spinning a wheel to win a random reward.",
    "Monopoly": "A board with dice rolls and moving a token around tiles.",
    "Pick-a-Box/Card": "AppMagic: players choose one container with random items or rewards from a set.",
    "Race": "AppMagic: leaderboards visualized as a race with a start and a finish; players advance by achieving event goals.",
    "Tabletop": "Tabletop or board-game style event that is not Monopoly (card games, board puzzles).",
    "Win Streak": "AppMagic: keeping or losing a win streak changes event progression.",
    "Leaderboard": "A ranked competition against other players by points or score that is not visualized as a race.",
    "Team Event": "Players cooperate in a team or club toward a shared goal or compete as teams.",
    "Pass": "A season or event pass with free and paid reward tracks.",
    "Other": "A LiveOps mechanic that fits none of the above.",
}

MOTIVATIONS = ["Collecting", "Competitive", "Cooperative", "Customizing", "Gambling", "Sense of FOMO", "Sense of achievement", "Sense of novelty", "Unique occasion"]

SCREEN_TYPES = {
    "event_intro": "Announcement or start pop-up that introduces the event and its rules.",
    "event_progress": "Event progress screen: milestones, progress bar, map or collected items.",
    "leaderboard": "Ranking or race screen with other players.",
    "rewards": "Reward, prize or results screen.",
    "event_offer": "Paid offer, bundle or store tied to the event.",
    "event_gameplay": "A level or board played inside the event.",
    "regular_gameplay": "Ordinary level or board with no event content in focus.",
    "home_or_menu": "Home screen, map, area or menu without an event screen in focus.",
    "other": "Anything else.",
}
