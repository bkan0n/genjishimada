from __future__ import annotations

from genjishimada_sdk.helpers import sanitize_string


def get_reward_url(type_: str, name: str) -> str:
    """Get the reward URL for a given type and name."""
    sanitized_name = sanitize_string(name)
    if type_ == "spray":
        url = f"https://cdn.genji.pk/assets/rank_card/spray/{sanitized_name}.webp"
    elif type_ == "skin":
        url = f"https://cdn.genji.pk/assets/rank_card/avatar/{sanitized_name}/heroic.webp"
    elif type_ == "pose":
        url = f"https://cdn.genji.pk/assets/rank_card/avatar/overwatch_1/{sanitized_name}.webp"
    elif type_ == "background":
        url = f"https://cdn.genji.pk/assets/rank_card/background/{sanitized_name}.webp"
    elif type_ == "coins":
        url = f"https://cdn.genji.pk/assets/rank_card/coins/{sanitized_name}.webp"
    else:
        url = ""
    return url
