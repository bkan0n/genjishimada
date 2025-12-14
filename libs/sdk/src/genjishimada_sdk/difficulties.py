from __future__ import annotations

from typing import Literal, TypeVar

__all__ = (
    "DIFFICULTY_COLORS",
    "DIFFICULTY_MIDPOINTS",
    "DIFFICULTY_RANGES_ALL",
    "DIFFICULTY_RANGES_TOP",
    "DIFFICULTY_TO_RANK_MAP",
    "DifficultyAll",
    "DifficultyTop",
    "Rank",
    "convert_extended_difficulty_to_top_level",
    "convert_raw_difficulty_to_difficulty_all",
    "convert_raw_difficulty_to_difficulty_top",
)
Rank = Literal["Ninja", "Jumper", "Skilled", "Pro", "Master", "Grandmaster", "God"]

DifficultyTop = Literal[
    "Easy",
    "Medium",
    "Hard",
    "Very Hard",
    "Extreme",
    "Hell",
]

DifficultyAll = Literal[
    "Easy -",
    "Easy",
    "Easy +",
    "Medium -",
    "Medium",
    "Medium +",
    "Hard -",
    "Hard",
    "Hard +",
    "Very Hard -",
    "Very Hard",
    "Very Hard +",
    "Extreme -",
    "Extreme",
    "Extreme +",
    "Hell",
]

D = TypeVar("D", DifficultyTop, DifficultyAll)

DIFFICULTY_RANGES_ALL: dict[DifficultyAll, tuple[float, float]] = {
    "Easy -": (0.0, 1.18),  # Beginner has been removed completely, so Easy - has absorbed that range.
    "Easy": (1.18, 1.76),
    "Easy +": (1.76, 2.35),
    "Medium -": (2.35, 2.94),
    "Medium": (2.94, 3.53),
    "Medium +": (3.53, 4.12),
    "Hard -": (4.12, 4.71),
    "Hard": (4.71, 5.29),
    "Hard +": (5.29, 5.88),
    "Very Hard -": (5.88, 6.47),
    "Very Hard": (6.47, 7.06),
    "Very Hard +": (7.06, 7.65),
    "Extreme -": (7.65, 8.24),
    "Extreme": (8.24, 8.82),
    "Extreme +": (8.82, 9.41),
    "Hell": (9.41, 10.0),
}

DIFFICULTY_RANGES_TOP: dict[DifficultyTop, tuple[float, float]] = {
    "Easy": (0.0, 2.35),  # Beginner has been removed completely, so Easy has absorbed that range.
    "Medium": (2.35, 4.12),
    "Hard": (4.12, 5.88),
    "Very Hard": (5.88, 7.65),
    "Extreme": (7.65, 9.41),
    "Hell": (9.41, 10.0),
}

DIFFICULTY_MIDPOINTS: dict[DifficultyAll, float] = {
    "Easy -": 0.89,  # Beginner removed completely, this midpoint ignores the old Beginner range.
    "Easy": 1.47,
    "Easy +": 2.06,
    "Medium -": 2.65,
    "Medium": 3.23,
    "Medium +": 3.83,
    "Hard -": 4.42,
    "Hard": 5.0,
    "Hard +": 5.58,
    "Very Hard -": 6.17,
    "Very Hard": 6.76,
    "Very Hard +": 7.36,
    "Extreme -": 7.95,
    "Extreme": 8.53,
    "Extreme +": 9.12,
    "Hell": 9.71,
}

DIFFICULTY_COLORS: dict[DifficultyAll, str] = {
    "Easy -": "#66ff66",
    "Easy": "#4dcc4d",
    "Easy +": "#33cc33",
    "Medium -": "#99ff33",
    "Medium": "#99e600",
    "Medium +": "#80cc00",
    "Hard -": "#ffd633",
    "Hard": "#ffb300",
    "Hard +": "#ff9900",
    "Very Hard -": "#ff8000",
    "Very Hard": "#e67e00",
    "Very Hard +": "#cc6600",
    "Extreme -": "#ff4d00",
    "Extreme": "#e04300",
    "Extreme +": "#b92d00",
    "Hell": "#990000",
}

DIFFICULTY_TO_RANK_MAP: dict[DifficultyTop, Rank] = {
    "Easy": "Jumper",
    "Medium": "Skilled",
    "Hard": "Pro",
    "Very Hard": "Master",
    "Extreme": "Grandmaster",
    "Hell": "God",
}


def _convert_raw_difficulty(mapping: dict[D, tuple[float, float]], raw_difficulty: float) -> D:
    for key, (low, high) in mapping.items():
        if low <= raw_difficulty < high:
            return key
    raise ValueError("Unknown difficulty")


def convert_raw_difficulty_to_difficulty_all(raw_difficulty: float) -> DifficultyAll:
    """Convert raw difficulty (float) into a DifficultyT string.

    This will match for the extended list of difficulties (-, +).
    """
    return _convert_raw_difficulty(DIFFICULTY_RANGES_ALL, raw_difficulty)


def convert_raw_difficulty_to_difficulty_top(raw_difficulty: float) -> DifficultyTop:
    """Convert raw difficulty (float) into a DifficultyT string.

    This will match only the top difficulties (excludes - and +).
    """
    return _convert_raw_difficulty(DIFFICULTY_RANGES_TOP, raw_difficulty)


def convert_extended_difficulty_to_top_level(extended_difficulty: DifficultyAll) -> DifficultyTop:
    """Convert extended difficulty (+ and -) into a top level DifficultyT string (no - or +)."""
    return extended_difficulty.replace(" +", "").replace(" -", "")  # pyright: ignore [reportReturnType]
