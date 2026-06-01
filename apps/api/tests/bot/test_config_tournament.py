"""Decode tests for the [channels.tournament] config block (D-01).

Verifies that both the dev and prod TOMLs decode into the bot ``Config`` struct with
``config.channels.tournament.announcements`` resolving to the per-environment channel id,
and that an unknown key under [channels.tournament] raises ``msgspec.ValidationError``
(forbid_unknown_fields is honored).
"""

from __future__ import annotations

import pathlib
import tomllib
from types import ModuleType

import msgspec
import pytest

_DEV_ANNOUNCEMENTS = 1377808369997447254
_PROD_ANNOUNCEMENTS = 975820285343301674


def _config_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "apps" / "bot" / "configs"


def _decode(bot_config_module: ModuleType, toml_path: pathlib.Path) -> object:
    data = tomllib.loads(toml_path.read_text())
    return msgspec.convert(data, bot_config_module.Config)


def test_dev_config_decodes_tournament_channel(
    bot_config_module: ModuleType, bot_repo_root: pathlib.Path
) -> None:
    """dev.toml decodes and exposes the dev tournament announcements channel id."""
    config = _decode(bot_config_module, _config_dir(bot_repo_root) / "dev.toml")
    announcements = config.channels.tournament.announcements
    assert isinstance(announcements, int)
    assert announcements == _DEV_ANNOUNCEMENTS


def test_prod_config_decodes_tournament_channel(
    bot_config_module: ModuleType, bot_repo_root: pathlib.Path
) -> None:
    """prod.toml decodes and exposes the prod tournament announcements channel id."""
    config = _decode(bot_config_module, _config_dir(bot_repo_root) / "prod.toml")
    announcements = config.channels.tournament.announcements
    assert isinstance(announcements, int)
    assert announcements == _PROD_ANNOUNCEMENTS


def test_tournament_block_forbids_unknown_fields(bot_config_module: ModuleType) -> None:
    """An unknown key under [channels.tournament] raises a ValidationError."""
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(
            {"announcements": 123, "unexpected_key": 456},
            bot_config_module.Tournament,
        )
